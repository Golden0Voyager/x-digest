"""
X (Twitter) 摘要生成器 - 主程序 (xAI 风格 UI + 稳定性增强版)

功能：极致交互界面 → 动态 Token 截断 → 入库合并 → 跨领域情报汇总
"""

import os
import asyncio
import json
import re
import time
import argparse
import sys
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
import questionary
import markdown

from config import (
    HOURS_LOOKBACK, ACCOUNT_SCAN_INTERVAL,
    AI_API_KEY, CACHE_RETENTION_HOURS
)
from fetcher import fetch_all_tweets
from pipeline import Color, log_print
from pipeline.orchestrator import run_pipeline

# 输出目录
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
OUTPUT_DIR.mkdir(exist_ok=True)

# ===== 日志系统（配置 file handler，log_print 从 pipeline 导入） =====
RUN_LOG_FILE = OUTPUT_DIR / "run.log"
logger = logging.getLogger("x_digest")
logger.setLevel(logging.INFO)
if not logger.handlers:
    file_handler = logging.FileHandler(RUN_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s'))
    logger.addHandler(file_handler)

CACHE_FILE = OUTPUT_DIR / "processed_tweets.json"
TWEET_POOL_FILE = OUTPUT_DIR / "raw_tweets_pool.json"
STATS_FILE = OUTPUT_DIR / "account_stats.json"

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_USER_ID = os.getenv("FEISHU_USER_ID", "")
FEISHU_CHAT_ID = os.getenv("FEISHU_CHAT_ID", "") # 新增：群聊 ID
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "") # 新增：Webhook 机器人 URL


# ===== 数据管理 (Cache & Pool) =====

def load_json(file_path: Path) -> dict:
    if file_path.exists():
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except:
            return {}
    return {}

def save_json(file_path: Path, data: dict):
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def clean_cache(cache: dict, hours: int) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    new_cache = {}
    for tid, ts_str in cache.items():
        try:
            if tid.startswith("SCAN_"):
                ts = datetime.fromisoformat(ts_str)
                if ts > (datetime.now(timezone.utc) - timedelta(hours=12)):
                    new_cache[tid] = ts_str
                continue
            ts = datetime.fromisoformat(ts_str)
            if ts > cutoff:
                new_cache[tid] = ts_str
        except: continue
    return new_cache

def clean_pool(pool: dict, hours: int) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    new_pool = {}
    for tid, tweet in pool.items():
        try:
            ts = datetime.fromisoformat(tweet["created_at"])
            if ts > cutoff:
                new_pool[tid] = tweet
        except: continue
    return new_pool


# ===== 账号健康度统计 =====

def update_account_health(username: str, tweets_found: list | None):
    """更新账号扫描健康度统计"""
    stats = load_json(STATS_FILE)
    now = datetime.now(timezone.utc).isoformat()
    if username not in stats:
        stats[username] = {
            "first_seen": now, "total_scans": 0, "success_scans": 0,
            "empty_scans": 0, "error_count": 0, "last_tweet_date": None,
            "tweet_counts_history": []
        }
    s = stats[username]
    s["total_scans"] += 1
    if tweets_found is not None:
        s["success_scans"] += 1
        s["error_count"] = 0
        count = len(tweets_found)
        if count > 0:
            s["last_tweet_date"] = now
        else:
            s["empty_scans"] += 1
        s["tweet_counts_history"] = (s.get("tweet_counts_history", []) + [count])[-10:]
    else:
        s["error_count"] += 1
    save_json(STATS_FILE, stats)


def generate_health_report(force=False):
    """生成账号健康审计报告（每 7 天自动触发一次）"""
    stats = load_json(STATS_FILE)
    if not stats:
        return
    report_flag = OUTPUT_DIR / ".last_health_report"
    if not force and report_flag.exists():
        try:
            if datetime.now(timezone.utc) - datetime.fromisoformat(report_flag.read_text().strip()) < timedelta(days=7):
                return
        except:
            pass
    log_print(f"\n {Color.CYAN}📋 生成账号健康审计报告...{Color.RESET}")
    ghosts, dormant, ranks = [], [], []
    now = datetime.now(timezone.utc)
    for u, d in stats.items():
        if d.get("error_count", 0) >= 5:
            ghosts.append(f"- @{u} (连续失败 {d['error_count']} 次)")
        elif d.get("last_tweet_date"):
            if now - datetime.fromisoformat(d["last_tweet_date"]) > timedelta(days=14):
                dormant.append(f"- @{u}")
        h = d.get("tweet_counts_history", [])
        if h:
            ranks.append((u, sum(h) / len(h)))
    ranks.sort(key=lambda x: x[1], reverse=True)
    report_md = [
        "# 🛡️ X-Digest 账号审计报告",
        f"> 日期：{datetime.now().strftime('%Y-%m-%d')}",
        "",
        "## 🚨 僵尸号（连续失败 5 次以上）",
        "\n".join(ghosts) if ghosts else "- 暂无",
        "",
        "## 💤 沉寂号（14 天无新推文）",
        "\n".join(dormant) if dormant else "- 暂无",
        "",
        "## 🔥 活跃度 TOP 10",
        "\n".join([f"- @{u} (平均 {r:.1f} 条/次)" for u, r in ranks[:10]]),
    ]
    (OUTPUT_DIR / "health_report.md").write_text("\n".join(report_md), encoding="utf-8")
    report_flag.write_text(now.isoformat())
    log_print(f" {Color.GREEN}✅ 审计报告已生成: {OUTPUT_DIR / 'health_report.md'}{Color.RESET}")


# ===== 飞书 API =====

def get_feishu_token() -> str:
    """获取飞书租户访问令牌，增加重试机制和代理支持"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with httpx.Client(trust_env=True) as client:
                resp = client.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
                    timeout=20,
                )
                # 先检查 HTTP 状态码，避免对 HTML 错误页调用 .json()
                if resp.status_code != 200:
                    body_preview = resp.text[:200].replace("\n", " ")
                    print(f"  {Color.YELLOW}⚠️  飞书 Token HTTP {resp.status_code} (尝试 {attempt+1}/{max_retries}): {body_preview}{Color.RESET}")
                    if attempt < max_retries - 1:
                        time.sleep(2)
                    continue

                try:
                    data = resp.json()
                except Exception as parse_err:
                    body_preview = resp.text[:200].replace("\n", " ")
                    print(f"  {Color.YELLOW}⚠️  飞书 Token JSON 解析失败 (尝试 {attempt+1}/{max_retries}): {parse_err} | 原始响应: {body_preview}{Color.RESET}")
                    if attempt < max_retries - 1:
                        time.sleep(2)
                    continue

                if data.get("code") == 0:
                    return data["tenant_access_token"]
                print(f"  {Color.YELLOW}⚠️  飞书 Token 业务码异常 (尝试 {attempt+1}/{max_retries}): {data}{Color.RESET}")
        except Exception as e:
            print(f"  {Color.YELLOW}⚠️  飞书 Token 请求异常 (尝试 {attempt+1}/{max_retries}): {e}{Color.RESET}")

        if attempt < max_retries - 1:
            time.sleep(2)

    raise Exception("多次尝试获取飞书 token 失败")

def send_feishu_message(text: str, msg_type: str = "text", content: dict | None = None, receive_id: str = None):
    # 优先使用传入的 receive_id，否则回退到配置文件
    target_id = receive_id or FEISHU_USER_ID
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, target_id]):
        print(f"{Color.GREY}⚠️  飞书配置不完整，跳过推送{Color.RESET}")
        return

    receive_id_type = "chat_id" if target_id.startswith("oc_") else "open_id"

    # 飞书消息安全截断
    if text and len(text) > 28000:
        text = text[:28000] + "\n\n... (内容过长已截断)"

    try:
        token = get_feishu_token()
        if content is None: content = {"text": text}
        with httpx.Client(trust_env=True) as client:
            resp = client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers={"Authorization": f"Bearer {token}"},
                json={"receive_id": target_id, "msg_type": msg_type, "content": json.dumps(content)},
                timeout=30,
            )
            if resp.status_code != 200:
                body_preview = resp.text[:200].replace("\n", " ")
                print(f"{Color.RED}⚠️  飞书消息 HTTP {resp.status_code}: {body_preview}{Color.RESET}")
                return

            try:
                data = resp.json()
            except Exception as parse_err:
                body_preview = resp.text[:200].replace("\n", " ")
                print(f"{Color.RED}⚠️  飞书消息 JSON 解析失败: {parse_err} | 原始响应: {body_preview}{Color.RESET}")
                return

            if data.get("code") == 0:
                msg_id = data.get("data", {}).get("message_id", "N/A")
                print(f"{Color.CYAN}📨 飞书消息推送成功！ (ID: {msg_id}){Color.RESET}")
            else:
                print(f"{Color.RED}⚠️  飞书消息推送失败: {data}{Color.RESET}")
    except Exception as e:
        print(f"{Color.RED}⚠️  飞书发送异常: {e}{Color.RESET}")


def send_feishu_webhook_card(title: str, doc_url: str, counts_text: str, hours: int, tweet_count: int):
    """通过 Webhook 发送精美的交互式卡片"""
    if not FEISHU_WEBHOOK_URL: return

    # 格式化领域统计，去掉 bullet 点以便卡片展示
    clean_counts = counts_text.replace("• ", "▫️ ")

    card_payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"🛰️ {title}"},
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**📊 汇总窗口**：过去 {hours} 小时\n**📡 发现信号**：{tweet_count} 条精选情报"
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**领域分布**：\n{clean_counts}"
                    }
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "📖 阅读完整内参"},
                            "type": "primary",
                            "url": doc_url
                        }
                    ]
                },
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": "Powered by x-digest · SenseNova (Token Plan + Distill) Enhanced"}]
                }
            ]
        }
    }

    try:
        with httpx.Client(trust_env=True) as client:
            resp = client.post(FEISHU_WEBHOOK_URL, json=card_payload, timeout=20)
            if resp.status_code != 200:
                body_preview = resp.text[:200].replace("\n", " ")
                print(f"{Color.RED}⚠️ Webhook HTTP {resp.status_code}: {body_preview}{Color.RESET}")
                return

            try:
                data = resp.json()
            except Exception as parse_err:
                body_preview = resp.text[:200].replace("\n", " ")
                print(f"{Color.RED}⚠️ Webhook JSON 解析失败: {parse_err} | 原始响应: {body_preview}{Color.RESET}")
                return

            if data.get("StatusCode") == 0 or data.get("code") == 0:
                print(f"{Color.CYAN}🪝 Webhook 卡片发送成功！{Color.RESET}")
            else:
                print(f"{Color.RED}⚠️ Webhook 发送失败: {data}{Color.RESET}")
    except Exception as e:
        print(f"{Color.RED}⚠️ Webhook 调用异常: {e}{Color.RESET}")


def upload_feishu_file(file_path: Path) -> str | None:
    """上传本地文件到飞书，返回 file_key"""
    if not file_path.exists(): return None
    try:
        token = get_feishu_token()
        url = "https://open.feishu.cn/open-apis/im/v1/files"
        headers = {"Authorization": f"Bearer {token}"}

        # 飞书上传文件需要 multipart/form-data
        files = {
            "file_type": (None, "pdf"),
            "file_name": (None, file_path.name),
            "file": (file_path.name, open(file_path, "rb"), "application/pdf")
        }

        with httpx.Client(trust_env=True) as client:
            resp = client.post(url, headers=headers, files=files, timeout=60)
            if resp.status_code != 200:
                body_preview = resp.text[:200].replace("\n", " ")
                print(f"  {Color.RED}⚠️  飞书文件上传 HTTP {resp.status_code}: {body_preview}{Color.RESET}")
                return None

            try:
                data = resp.json()
            except Exception as parse_err:
                body_preview = resp.text[:200].replace("\n", " ")
                print(f"  {Color.RED}⚠️  飞书文件上传 JSON 解析失败: {parse_err} | 原始响应: {body_preview}{Color.RESET}")
                return None

            if data.get("code") == 0:
                return data["data"]["file_key"]
            else:
                print(f"  {Color.RED}⚠️  飞书文件上传失败: {data}{Color.RESET}")
    except Exception as e:
        print(f"  {Color.RED}⚠️  飞书上传异常: {e}{Color.RESET}")
    return None


def create_feishu_doc(title: str, markdown_content: str) -> str | None:
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET]): return None
    try:
        token = get_feishu_token()
        headers = {"Authorization": f"Bearer {token}"}
        # 增加整体超时时间
        with httpx.Client(trust_env=True, headers=headers) as client:
            # 1. 创建文档 (超时增加到 60s)
            try:
                resp = client.post("https://open.feishu.cn/open-apis/docx/v1/documents", json={"title": title}, timeout=60)
                data = resp.json()
                if data.get("code") != 0:
                    print(f"  {Color.RED}⚠️  飞书文档创建失败: {data}{Color.RESET}")
                    return None
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                print(f"  {Color.RED}⚠️  飞书文档创建网络异常: {e}{Color.RESET}")
                return None

            doc_id = data["data"]["document"]["document_id"]
            doc_url = f"https://www.feishu.cn/docx/{doc_id}"

            lines = markdown_content.strip().split("\n")
            children = []
            # ... (解析逻辑保持不变，但增加容错)
            for line in lines:
                stripped = line.strip()
                if not stripped: continue
                if stripped.startswith("### "):
                    children.append({"block_type": 5, "heading3": {"elements": [{"text_run": {"content": stripped[4:]}}], "style": {}}})
                elif stripped.startswith("## "):
                    children.append({"block_type": 4, "heading2": {"elements": [{"text_run": {"content": stripped[3:]}}], "style": {}}})
                elif stripped.startswith("# "):
                    children.append({"block_type": 3, "heading1": {"elements": [{"text_run": {"content": stripped[2:]}}], "style": {}}})
                elif stripped.startswith("---"):
                    children.append({"block_type": 22, "divider": {}})
                elif stripped.startswith("- "):
                    children.append({"block_type": 2, "text": {"elements": [{"text_run": {"content": f"• {stripped[2:]}"}}], "style": {}}})
                else:
                    # 增强版解析器：识别 **加粗** 和 _斜体_ (支持方案 B: **_text_**)
                    elements = []
                    pattern = r'(\*\*_([^*_]+)_\*\*)|(\*\*([^*]+)\*\*)|(_([^_]+)_)'
                    last_end = 0
                    for match in re.finditer(pattern, stripped):
                        if match.start() > last_end:
                            elements.append({"text_run": {"content": stripped[last_end:match.start()]}})

                        full_match = match.group(0)
                        if full_match.startswith("**_") and full_match.endswith("_**"):
                            elements.append({"text_run": {"content": match.group(2), "text_element_style": {"bold": True, "italic": True}}})
                        elif full_match.startswith("**") and full_match.endswith("**"):
                            elements.append({"text_run": {"content": match.group(4), "text_element_style": {"bold": True}}})
                        elif full_match.startswith("_") and full_match.endswith("_"):
                            elements.append({"text_run": {"content": match.group(6), "text_element_style": {"italic": True}}})
                        last_end = match.end()

                    if last_end < len(stripped):
                        elements.append({"text_run": {"content": stripped[last_end:]}})

                    children.append({"block_type": 2, "text": {"elements": elements if elements else [{"text_run": {"content": stripped}}], "style": {}}})

            # 2. 批量写入块 (使用更稳健的分批逻辑和重试)
            batch_size = 20 # 进一步减小每批大小以提高稳定性
            for i in range(0, len(children), batch_size):
                chunk = children[i : i + batch_size]
                success = False
                for attempt in range(3): # 增加重试到 3 次
                    try:
                        resp = client.post(
                            f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                            json={"children": chunk},
                            timeout=60
                        )
                        # 防御空响应或异常响应
                        if not resp or not resp.text:
                            raise Exception("飞书返回空响应 (可能是代理或网络波动)")

                        data = resp.json()
                        if data.get("code") == 0:
                            success = True
                            break
                        else:
                            print(f"  {Color.YELLOW}⚠️  块写入失败 (尝试 {attempt+1}/3): {data}{Color.RESET}")
                    except (httpx.TimeoutException, httpx.ConnectError) as e:
                        print(f"  {Color.YELLOW}⚠️  块写入网络/超时异常 (尝试 {attempt+1}/3): {e}{Color.RESET}")
                    except Exception as e:
                        print(f"  {Color.YELLOW}⚠️  块写入未知异常 (尝试 {attempt+1}/3): {e}{Color.RESET}")

                    time.sleep(1.5 * (attempt + 1)) # 指数级后退

                if not success:
                    print(f"  {Color.RED}❌ 部分文档块写入最终失败，文档可能不完整{Color.RESET}")

                # 批次之间增加微小延迟，防止触发频率限制
                time.sleep(0.5)

            return doc_url
    except Exception as e:
        print(f"  {Color.YELLOW}⚠️  飞书文档流程异常: {e}{Color.RESET}")
        return None


# ===== AI 处理 =====

async def render_markdown_to_pdf(md_path: Path):
    try:
        from playwright.async_api import async_playwright
        import markdown
        pdf_path = md_path.with_suffix(".pdf")
        md_content = md_path.read_text(encoding="utf-8")
        html_body = markdown.markdown(md_content, extensions=["extra", "codehilite", "toc"])
        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 900px; margin: 0 auto; padding: 40px; }}
                h1 {{ color: #1a73e8; border-bottom: 2px solid #e8eaed; padding-bottom: 10px; }}
                h2 {{ color: #202124; margin-top: 30px; border-left: 5px solid #1a73e8; padding-left: 15px; }}
                h3 {{ color: #1a73e8; margin-top: 25px; border-bottom: 1px solid #f1f3f4; padding-bottom: 5px; }}
                blockquote {{ background: #f8f9fa; border-left: 10px solid #ccc; margin: 1.5em 10px; padding: 0.5em 10px; color: #555; font-style: italic; }}
                hr {{ border: 0; height: 1px; background: #e8eaed; margin: 20px 0; }}
                strong {{ color: #1a73e8; }}
                img {{ max-width: 100%; height: auto; display: block; margin: 10px 0; border-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
            </style>
        </head>
        <body>{html_body}</body>
        </html>
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            # 设置内容，使用 networkidle 确保资源尽量加载，但增加容错
            try:
                await page.set_content(full_html, timeout=60000, wait_until="networkidle")
            except Exception as e:
                from playwright.async_api import TimeoutError
                if isinstance(e, TimeoutError):
                    print(f"  {Color.YELLOW}⚠️  PDF 渲染中部分图片加载超时，将继续生成已有内容...{Color.RESET}")
                else:
                    raise e

            await page.wait_for_timeout(2000) # 额外多等 2s 确保渲染
            await page.pdf(path=str(pdf_path), format="A4", margin={"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"}, print_background=True)
            await browser.close()
            print(f"{Color.CYAN}📄 已同步生成 PDF：{pdf_path}{Color.RESET}")
            return pdf_path
    except Exception as e:
        print(f"{Color.YELLOW}⚠️  PDF 生成失败: {e}{Color.RESET}")
        return None

def sync_to_wiki(topic: str, content: str, metadata: dict):
    """将摘要同步到 agent_platform 的 WikiAgent"""
    if os.getenv("GITHUB_ACTIONS") == "true":
        return
    try:
        url = "http://localhost:8000/api/v1/wiki/ingest"
        payload = {
            "source_project": "x_digest",
            "topic": topic,
            "content": content,
            "metadata": metadata
        }
        with httpx.Client() as client:
            resp = client.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                print(f" {Color.GREEN}📡 WikiAgent Sync Successful!{Color.RESET}")
            else:
                print(f" {Color.YELLOW}⚠️ WikiAgent Sync Failed: {resp.status_code}{Color.RESET}")
    except Exception as e:
        print(f" {Color.RED}⚠️ WikiAgent Connection Error: {e}{Color.RESET}")

def save_output(content: str, tweet_count: int, hours: int, selected_domains: list[str] | None = None, account_count: int = 0) -> Path:
    date = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M")
    output_path = OUTPUT_DIR / f"{date}-{time_str}.md"

    # 构造领域描述
    domain_mapping = {
        "AI_Scientists_&_Academia": "AI 科学家",
        "Tech_Industry_&_CEOs": "科技巨头 & CEO",
        "Macro_Finance_&_A-Shares": "宏观金融",
        "Tech_Media_&_Deep_Analysis": "科技媒体",
        "F1_Racing_&_Paddock": "F1 赛车",
        "Contemporary_Art_&_Institutions": "当代艺术"
    }
    if selected_domains:
        domain_labels = [domain_mapping.get(d, d) for d in selected_domains]
        domain_str = ", ".join(domain_labels)
    else:
        domain_str = "全领域全量扫描"

    header = f"# 🛰️ X-Digest 科技汇总日报\n"
    header += f"> **📅 生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    header += f"> **📊 汇总窗口**：过去 {hours} 小时 | {domain_str} ({account_count} 账号) | {tweet_count} 条推文\n"
    header += f"> **📡 数据来源**：X.com (中英对照版)\n\n---\n\n"

    output_path.write_text(header + content, encoding="utf-8")
    print(f"{Color.GREEN}💾 已保存精美排版报告：{output_path}{Color.RESET}")
    return output_path


# ===== 主函数 =====

def main():
    parser = argparse.ArgumentParser(description="X-Digest 推文摘要生成器")
    parser.add_argument("--manual", action="store_true", help="手动模式：扫描所有领域")
    parser.add_argument("--hours", type=int, default=None, help=f"回溯小时数 (默认 {HOURS_LOOKBACK})")
    parser.add_argument("--force", action="store_true", help="强制模式：忽略冷却时间")
    parser.add_argument("--fetch-only", action="store_true", help="仅执行抓取，不运行 AI 管线")
    parser.add_argument("--pipeline-only", action="store_true", help="仅运行 AI 管线，读取已有缓存")
    parser.add_argument("--no-pdf", action="store_true", help="跳过 PDF 生成，仅输出 Markdown")
    args = parser.parse_args()

    if args.fetch_only and args.pipeline_only:
        print(f"{Color.RED}❌ --fetch-only 和 --pipeline-only 不能同时指定{Color.RESET}")
        return

    # 1. 矩阵风格开屏
    if not args.manual and sys.stdin.isatty():
        os.system('clear' if os.name == 'posix' else 'cls')

        print(f"{Color.MATRIX_GREEN}")
        logo = [
            r" ██╗  ██╗       ██████╗ ██╗ ██████╗ ███████╗███████╗████████╗",
            r" ╚██╗██╔╝       ██╔══██╗██║██╔════╝ ██╔════╝██╔════╝╚══██╔══╝",
            r"  ╚███╔╝███████╗██║  ██║██║██║  ███╗█████╗  ███████╗   ██║   ",
            r"  ██╔██╗╚══════╝██║  ██║██║██║   ██║██╔══╝  ╚════██║   ██║   ",
            r" ██╔╝ ██╗       ██████╔╝██║╚██████╔╝███████╗███████║   ██║   ",
            r" ╚═╝  ╚═╝       ╚═════╝ ╚═╝ ╚═════╝ ╚══════╝╚══════╝   ╚═╝   "
        ]
        for line in logo: print(line)
        print(f"\n {Color.BOLD}COMMAND CENTER v3.0 // NEURAL LINK ACTIVE{Color.RESET}")
        print(f" {Color.MATRIX_GREEN} ──────────────────────────────────────────────────{Color.RESET}")

        print(f"\n {Color.RED}{Color.BOLD} [!] LEGAL COMPLIANCE PROTOCOL{Color.RESET}")
        print(f" {Color.MATRIX_GREEN} ├─{Color.RESET} {Color.GREY}Research & Learning use only.{Color.RESET}")
        print(f" {Color.MATRIX_GREEN} ├─{Color.RESET} {Color.GREY}Assess risks of simulation individually.{Color.RESET}")
        print(f" {Color.MATRIX_GREEN} └─{Color.RESET} {Color.GREY}No responsibility for account status.{Color.RESET}")
        print(f" {Color.MATRIX_GREEN} ──────────────────────────────────────────────────{Color.RESET}")

        is_agreed = questionary.confirm(
            "➔ Agree and Establish Connection?",
            default=True,
            auto_enter=True,
            style=questionary.Style([
                ('answer', 'fg:#00ff00 bold'),
                ('question', 'fg:#ffffff'),
            ])
        ).ask()

        if not is_agreed:
            print(f"\n {Color.RED}Process Terminated.{Color.RESET}")
            return

        # 领域多选 (矩阵绿风格)
        domain_mapping = {
            "AI_Scientists_&_Academia": "AI Scientists & Academia",
            "Tech_Industry_&_CEOs": "Tech Giants & OEMs",
            "Macro_Finance_&_A-Shares": "Macro Finance & Alpha",
            "Tech_Media_&_Deep_Analysis": "Media & Deep Analysis",
            "F1_Racing_&_Paddock": "F1 Paddock Dynamics",
            "Contemporary_Art_&_Institutions": "Contemporary Art"
        }

        # 加载分类账号
        CUSTOM_ACCOUNTS_FILE = Path("custom_accounts.json")
        categorized_accounts = {}
        if CUSTOM_ACCOUNTS_FILE.exists():
            categorized_accounts = json.loads(CUSTOM_ACCOUNTS_FILE.read_text(encoding="utf-8"))

        choices = []
        # 定义默认不勾选的领域
        unchecked_domains = ["F1_Racing_&_Paddock", "Contemporary_Art_&_Institutions"]

        for key, label in domain_mapping.items():
            count = len(categorized_accounts.get(key, {}))
            if count > 0:
                is_checked = key not in unchecked_domains
                choices.append(questionary.Choice(f"{label} [{count}]", value=key, checked=is_checked))

        selected_keys = questionary.checkbox(
            "Select Intelligence Sectors:",
            choices=choices,
            style=questionary.Style([
                ('checkbox', 'fg:#00ff00'),
                ('pointer', 'fg:#00ff00 bold'),
                ('highlighted', 'fg:#00ff00'),
                ('selected', 'fg:#00ff00'),
                ('text', 'fg:#ffffff'),
            ])
        ).ask()
        if not selected_keys:
            print(f"\n {Color.RED}Null Sector Error.{Color.RESET}")
            return

        selected_accounts = {}
        for key in selected_keys:
            selected_accounts.update(categorized_accounts.get(key, {}))

        # 历史回看模式选择
        args.target_date = None
        if questionary.confirm("Generate a report for a specific historical date?", default=False).ask():
            date_str = questionary.text("Enter target date (YYYY-MM-DD):", default=datetime.now().strftime("%Y-%m-%d")).ask()
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
                args.target_date = date_str
            except ValueError:
                print(f"\n {Color.RED}Invalid date format. Falling back to live mode.{Color.RESET}")
                args.hours = int(questionary.text("Retroactive Hours:", default=str(HOURS_LOOKBACK)).ask())
        else:
            args.hours = int(questionary.text("Retroactive Hours:", default=str(HOURS_LOOKBACK)).ask())

        args.force = questionary.confirm("Bypass Cooldown?", default=False).ask() if not args.target_date else False
    else:
        # 非交互模式：分组结构默认选择全部领域
        custom_accounts_file = Path("custom_accounts.json")
        default_accounts_file = Path("defaults/suggested_accounts.json")

        raw_data = None
        if custom_accounts_file.exists():
            raw_data = json.loads(custom_accounts_file.read_text(encoding="utf-8"))
            print(f" {Color.GREY}📚 非交互模式账号源：custom_accounts.json{Color.RESET}")
        elif default_accounts_file.exists():
            raw_data = json.loads(default_accounts_file.read_text(encoding="utf-8"))
            print(f" {Color.GREY}📚 非交互模式账号源：defaults/suggested_accounts.json{Color.RESET}")

        if isinstance(raw_data, dict) and raw_data:
            # 兼容两种格式：
            # 1) 分组结构: {"DomainA": {"user1": "...", ...}, ...}
            # 2) 扁平结构: {"user1": "...", "user2": "...", ...}
            sample_val = next(iter(raw_data.values()))
            if isinstance(sample_val, dict):
                selected_keys = list(raw_data.keys())
                selected_accounts = {}
                for key in selected_keys:
                    v = raw_data.get(key, {})
                    if isinstance(v, dict):
                        selected_accounts.update(v)
            else:
                selected_accounts = raw_data
                selected_keys = None
        else:
            from config import ACCOUNTS
            selected_accounts = ACCOUNTS
            selected_keys = None

        print(f" {Color.GREY}📌 非交互模式已加载 {len(selected_accounts)} 个账号{Color.RESET}")
        if not hasattr(args, "target_date"):
            args.target_date = None

    # 3. 引擎启动与账号过滤
    if args.hours is None and not args.target_date:
        args.hours = HOURS_LOOKBACK

    cache = load_json(CACHE_FILE)
    pool = load_json(TWEET_POOL_FILE)

    if args.target_date:
        print(f"\n {Color.CYAN}✨ Historical Mode Initiated:{Color.RESET} Extracting signals from {args.target_date}")
        target_start = datetime.strptime(args.target_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        target_end = target_start + timedelta(days=1)

        selected_tweets = []
        for tweet in pool.values():
            try:
                ts = datetime.fromisoformat(tweet["created_at"])
                if target_start <= ts < target_end and tweet["username"] in selected_accounts:
                    selected_tweets.append(tweet)
            except: pass

        print(f"\n {Color.BOLD}📊 Data Aggregation:{Color.RESET} {len(selected_tweets)} valid signal(s) found for {args.target_date}.")

        if not selected_tweets:
            print(f" {Color.YELLOW}No signals recorded for this date.{Color.RESET}")
            return

        summary, counts_text = asyncio.run(run_pipeline(selected_tweets))
        output_path = save_output(summary, len(selected_tweets), 24, selected_domains=selected_keys, account_count=len(selected_accounts))
        asyncio.run(render_markdown_to_pdf(output_path))

        doc_url = create_feishu_doc(f"X 情报大合拢 ({args.target_date})", summary)
        msg = f"📰 X 情报历史报告 ({args.target_date})\n\n📊 领域分布：\n{counts_text}\n\n📄 完整情报：{doc_url if doc_url else '见本地 output/'}"
        send_feishu_message(msg)
        print(f"\n {Color.GREEN}✅ Historical Report Accomplished.{Color.RESET}")
        return

    # ===== 抓取阶段（可被 --pipeline-only 跳过） =====
    if not args.pipeline_only:
        # 过滤冷却时间内的账号
        active_accounts = []
        if not args.force:
            for acc in selected_accounts.keys():
                scan_key = f"SCAN_{acc}"
                if scan_key in cache:
                    try:
                        last_scan = datetime.fromisoformat(cache[scan_key])
                        if datetime.now(timezone.utc) - last_scan < timedelta(hours=ACCOUNT_SCAN_INTERVAL):
                            continue
                    except: pass
                active_accounts.append(acc)
            skipped_count = len(selected_accounts) - len(active_accounts)
            if skipped_count > 0:
                print(f" {Color.GREY}⏩ Skipping {skipped_count} nodes recently synced. (Cooldown Active){Color.RESET}")
        else:
            active_accounts = list(selected_accounts.keys())

        print(f"\n {Color.CYAN}✨ Deployment Initiated:{Color.RESET} {len(active_accounts)} active nodes | {args.hours}h window")

        def on_fetch_success(username, tweets_found):
            update_account_health(username, tweets_found)
            if tweets_found is None:
                return
            now_iso = datetime.now(timezone.utc).isoformat()
            cache[f"SCAN_{username}"] = now_iso
            for t in tweets_found:
                if t["tweet_id"] not in cache: cache[t["tweet_id"]] = now_iso
                pool[t["tweet_id"]] = t
            save_json(CACHE_FILE, clean_cache(cache, CACHE_RETENTION_HOURS))
            save_json(TWEET_POOL_FILE, clean_pool(pool, CACHE_RETENTION_HOURS))

        print(f" {Color.GREY}📡 Syncing live data from {len(active_accounts)} targets...{Color.RESET}\n")
        asyncio.run(fetch_all_tweets(accounts_list=active_accounts, on_success=on_fetch_success, hours_lookback=args.hours))

        pool = clean_pool(pool, CACHE_RETENTION_HOURS)
        save_json(TWEET_POOL_FILE, pool)

    if args.fetch_only:
        print(f"\n {Color.GREEN}✅ Fetch-only 模式完成，已更新缓存。{Color.RESET}")
        return

    # AI 管线需要 API Key，在此处检查避免 fetch-only 模式也被阻断
    if not AI_API_KEY:
        print(f"\n {Color.RED}🚨 CRITICAL ERROR: AI_API_KEY Not Found.{Color.RESET}")
        print(f" {Color.GREY}└─ {Color.RESET}Please check your .env file and ensure AI_API_KEY is properly set.")
        sys.exit(1)

    if args.pipeline_only:
        pool = load_json(TWEET_POOL_FILE)
        print(f"\n {Color.CYAN}🔄 Pipeline-only 模式：从缓存加载 {len(pool)} 条推文{Color.RESET}")

    # ===== 管线阶段（可被 --fetch-only 跳过） =====
    # 仅保留本次选中的账号，且在回看时间窗口内的推文
    now = datetime.now(timezone.utc)
    lookback_delta = timedelta(hours=args.hours)
    selected_tweets = []
    for tweet in pool.values():
        try:
            ts = datetime.fromisoformat(tweet["created_at"])
            # 对齐历史模式逻辑：过滤账号 + 过滤时间
            if (now - ts <= lookback_delta) and (tweet["username"] in selected_accounts):
                selected_tweets.append(tweet)
        except: pass

    print(f"\n {Color.BOLD}📊 Data Aggregation:{Color.RESET} {len(selected_tweets)} valid signal(s) found.")

    if not selected_tweets:
        print(f" {Color.GREEN}System standby. No new signals.{Color.RESET}")
        status_msg = (
            f"🟡 X 情报汇总状态更新 ({args.hours}h)\n\n"
            f"- 扫描账号：{len(selected_accounts)}\n"
            f"- 活跃节点：{'N/A (pipeline-only)' if args.pipeline_only else len(active_accounts)}\n"
            f"- 新信号：0\n\n"
            "本次窗口内未发现新推文，系统已待机。"
        )
        send_feishu_message(status_msg)
        return

    summary, counts_text = asyncio.run(run_pipeline(selected_tweets))
    output_path = save_output(summary, len(selected_tweets), args.hours, selected_domains=selected_keys, account_count=len(selected_accounts))

    # 同步至 WikiAgent
    sync_to_wiki(topic=f"X情报汇总_{args.hours}h", content=summary, metadata={"domains": selected_keys, "tweet_count": len(selected_tweets)})

    if not args.no_pdf:
        asyncio.run(render_markdown_to_pdf(output_path))

    date_label = datetime.now().strftime("%Y-%m-%d")
    doc_url = create_feishu_doc(f"X 情报大合拢 ({args.hours}h) · {date_label}", summary)

    msg = f"📰 X 情报汇总报告 ({args.hours}h)\n\n📊 领域分布：\n{counts_text}\n\n📄 完整情报：{doc_url if doc_url else '见本地 output/'}"

    # 1. 发送私聊文字消息
    send_feishu_message(msg)

    # 2. 发送 Webhook 卡片（如果配置了 URL）
    if FEISHU_WEBHOOK_URL and doc_url:
        send_feishu_webhook_card(f"X-Digest 科技汇总日报", doc_url, counts_text, args.hours, len(selected_tweets))

    # 3. 如果配置了群 ID，发送 PDF 文件到群
    if FEISHU_CHAT_ID and output_path:
        pdf_path = output_path.with_suffix(".pdf")
        if pdf_path.exists():
            print(f" {Color.GREY}📦 正在上传 PDF 报告至飞书群...{Color.RESET}")
            file_key = upload_feishu_file(pdf_path)
            if file_key:
                send_feishu_message("", msg_type="file", content={"file_key": file_key}, receive_id=FEISHU_CHAT_ID)
                # 同时在群里发一条文字说明
                send_feishu_message(f"📊 以上是今日 X-Digest PDF 报告\n回溯窗口：{args.hours}h\n推文总数：{len(selected_tweets)}", receive_id=FEISHU_CHAT_ID)

    generate_health_report()
    print(f"\n {Color.GREEN}✅ Mission Accomplished.{Color.RESET}")

if __name__ == "__main__":
    main()
