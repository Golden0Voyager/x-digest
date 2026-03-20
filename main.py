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
from pipeline.orchestrator import run_pipeline

# ANSI 色彩代码
class Color:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    MATRIX_GREEN = "\033[38;5;46m"  # 矩阵经典亮绿
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    RESET = "\033[0m"
    GREY = "\033[90m"

# AI 客户端初始化 (支持任何兼容 OpenAI 协议的服务商)
if not AI_API_KEY:
    print(f"\n {Color.RED}🚨 CRITICAL ERROR: AI_API_KEY Not Found.{Color.RESET}")
    print(f" {Color.GREY}└─ {Color.RESET}Please check your .env file and ensure AI_API_KEY is properly set.")
    sys.exit(1)

# 输出目录
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
OUTPUT_DIR.mkdir(exist_ok=True)

CACHE_FILE = OUTPUT_DIR / "processed_tweets.json"
TWEET_POOL_FILE = OUTPUT_DIR / "raw_tweets_pool.json"

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_USER_ID = os.getenv("FEISHU_USER_ID", "")


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


# ===== 飞书 API =====

def get_feishu_token() -> str:
    """获取飞书租户访问令牌，增加重试机制和代理支持"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 允许使用系统代理 (trust_env=True)
            with httpx.Client(trust_env=True) as client:
                resp = client.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
                    timeout=20, # 增加超时到 20s
                )
                data = resp.json()
                if data.get("code") == 0:
                    return data["tenant_access_token"]
                print(f"  {Color.YELLOW}⚠️  飞书 Token 响应异常 (尝试 {attempt+1}/{max_retries}): {data}{Color.RESET}")
        except Exception as e:
            print(f"  {Color.YELLOW}⚠️  飞书 Token 获取网络异常 (尝试 {attempt+1}/{max_retries}): {e}{Color.RESET}")
        
        if attempt < max_retries - 1:
            time.sleep(2) # 重试前等待
    
    raise Exception("多次尝试获取飞书 token 失败")

def send_feishu_message(text: str, msg_type: str = "text", content: dict | None = None):
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_ID]):
        print(f"{Color.GREY}⚠️  飞书配置不完整，跳过推送{Color.RESET}")
        return
    
    # 飞书消息安全截断
    if text and len(text) > 28000:
        text = text[:28000] + "\n\n... (内容过长已截断)"

    try:
        token = get_feishu_token()
        if content is None: content = {"text": text}
        with httpx.Client(trust_env=True) as client:
            resp = client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "open_id"},
                headers={"Authorization": f"Bearer {token}"},
                json={"receive_id": FEISHU_USER_ID, "msg_type": msg_type, "content": json.dumps(content)},
                timeout=30, # 增加到 30s
            )
            if resp.json().get("code") == 0:
                print(f"{Color.CYAN}📨 飞书消息推送成功！{Color.RESET}")
            else:
                print(f"{Color.RED}⚠️  飞书消息推送失败: {resp.json()}{Color.RESET}")
    except Exception as e:
        print(f"{Color.RED}⚠️  飞书发送异常: {e}{Color.RESET}")


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
    args = parser.parse_args()

    # 1. 矩阵风格开屏
    if not any([args.manual, args.hours is not None, args.force]):
        os.system('clear' if os.name == 'posix' else 'cls')
        
        print(f"\n {Color.MATRIX_GREEN} [  LOADING X-DIGEST CORE...  ]{Color.RESET}")
        time.sleep(0.3)
        print(f" {Color.MATRIX_GREEN} > Establishing secure tunnel...{Color.RESET}")
        time.sleep(0.4)
        print(f" {Color.MATRIX_GREEN} > Synchronizing with X-Network...{Color.RESET}")
        time.sleep(0.3)
        
        # 完美对齐的中空风格 ASCII Art
        matrix_logo = rf"""{Color.MATRIX_GREEN}{Color.BOLD}
  __  __      _____  _____  _____  ______  _____  _______ 
  \ \/ /     |  __ \|_   _|/ ____||  ____|/ ____||__   __|
   \  /______| |  | | | | | |  __ | |__  | (___     | |   
   /  \______| |  | | | | | | |_ ||  __|  \___ \    | |   
  / /\ \     | |__| |_| |_| |__| || |____ ____) |   | |   
 /_/  \_\    |_____/|_____|\_____||______|_____/    |_|   {Color.RESET}"""
        print(matrix_logo)
        print(f"\n {Color.MATRIX_GREEN} {Color.BOLD}COMMAND CENTER v2.2 // NEURAL LINK ACTIVE{Color.RESET}")
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
        # 非交互模式
        selected_keys = None
        CUSTOM_ACCOUNTS_FILE = Path("custom_accounts.json")
        if CUSTOM_ACCOUNTS_FILE.exists():
            raw_data = json.loads(CUSTOM_ACCOUNTS_FILE.read_text(encoding="utf-8"))
            selected_accounts = {}
            for v in raw_data.values():
                if isinstance(v, dict): selected_accounts.update(v)
        else:
            from config import ACCOUNTS
            selected_accounts = ACCOUNTS
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

    # 过滤冷却时间内的账号 (仅在非历史模式)
    active_accounts = []
    if not args.force:
        for acc in selected_accounts.keys():
            scan_key = f"SCAN_{acc}"
            if scan_key in cache:
                try:
                    last_scan = datetime.fromisoformat(cache[scan_key])
                    if datetime.now(timezone.utc) - last_scan < timedelta(hours=ACCOUNT_SCAN_INTERVAL):
                        # 仅在交互模式下提示跳过
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
        return

    summary, counts_text = asyncio.run(run_pipeline(selected_tweets))
    output_path = save_output(summary, len(selected_tweets), args.hours, selected_domains=selected_keys, account_count=len(selected_accounts))
    asyncio.run(render_markdown_to_pdf(output_path))
    
    date_label = datetime.now().strftime("%Y-%m-%d")
    doc_url = create_feishu_doc(f"X 情报大合拢 ({args.hours}h) · {date_label}", summary)
    
    msg = f"📰 X 情报汇总报告 ({args.hours}h)\n\n📊 领域分布：\n{counts_text}\n\n📄 完整情报：{doc_url if doc_url else '见本地 output/'}"
    send_feishu_message(msg)
    print(f"\n {Color.GREEN}✅ Mission Accomplished.{Color.RESET}")

if __name__ == "__main__":
    main()
