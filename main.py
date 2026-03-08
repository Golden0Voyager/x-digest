"""
X (Twitter) 摘要生成器 - 主程序 (支持增量抓取与缓存)

抓取推文 → 过滤缓存 → 翻译 → 总结 → 输出 → 飞书推送
"""

import os
import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from openai import OpenAI
from dotenv import load_dotenv

from config import SUMMARY_PROMPT, HOURS_LOOKBACK
from fetcher import fetch_all_tweets

# 加载环境变量
load_dotenv()

# Groq API (兼容 OpenAI 格式)
groq_client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)

# 输出目录
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
OUTPUT_DIR.mkdir(exist_ok=True)

# 缓存文件
CACHE_FILE = OUTPUT_DIR / "processed_tweets.json"

# 飞书配置
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_USER_ID = os.getenv("FEISHU_USER_ID", "")


# ===== 缓存管理 =====

def load_cache() -> dict:
    """加载已处理推文的缓存"""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except:
            return {}
    return {}


def save_cache(cache: dict):
    """保存缓存"""
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_cache(cache: dict) -> dict:
    """清理超过 HOURS_LOOKBACK 的旧缓存"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_LOOKBACK)
    new_cache = {}
    for tid, ts_str in cache.items():
        try:
            # 允许特殊前缀 SCAN_ 开头的记录（账号扫描记录）
            if tid.startswith("SCAN_"):
                # 扫描记录如果超过 12 小时可以自动清除，以便第二天重扫
                ts = datetime.fromisoformat(ts_str)
                if ts > (datetime.now(timezone.utc) - timedelta(hours=12)):
                    new_cache[tid] = ts_str
                continue

            if not isinstance(ts_str, str):
                new_cache[tid] = datetime.now(timezone.utc).isoformat()
                continue
            ts = datetime.fromisoformat(ts_str)
            if ts > cutoff:
                new_cache[tid] = ts_str
        except:
            continue
    return new_cache


# ===== 飞书 API =====

def get_feishu_token() -> str:
    """获取飞书 tenant_access_token (强制直连)"""
    try:
        with httpx.Client(trust_env=False) as client:
            resp = client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
                timeout=10,
            )
            data = resp.json()
            if data.get("code") == 0:
                return data["tenant_access_token"]
            raise Exception(f"获取飞书 token 失败: {data}")
    except Exception as e:
        print(f"  ⚠️  飞书 Token 获取异常: {e}")
        raise


def send_feishu_message(text: str, msg_type: str = "text", content: dict | None = None):
    """通过机器人给用户发飞书消息 (强制直连)"""
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_ID]):
        print("⚠️  飞书配置不完整，跳过推送")
        return

    try:
        token = get_feishu_token()
        if content is None:
            content = {"text": text}
        
        with httpx.Client(trust_env=False) as client:
            resp = client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "open_id"},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": FEISHU_USER_ID,
                    "msg_type": msg_type,
                    "content": json.dumps(content),
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("code") == 0:
                print("📨 飞书消息推送成功！")
            else:
                print(f"⚠️  飞书推送失败: {data.get('msg', data)}")
    except Exception as e:
        print(f"⚠️  飞书发送异常: {e}")


def create_feishu_doc(title: str, markdown_content: str) -> str | None:
    """创建飞书文档并写入内容 (强制直连 + 深度转换 + 分批写入)"""
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET]):
        return None

    try:
        token = get_feishu_token()
        headers = {"Authorization": f"Bearer {token}"}

        # 1. 创建空文档
        with httpx.Client(trust_env=False, headers=headers) as client:
            resp = client.post(
                "https://open.feishu.cn/open-apis/docx/v1/documents",
                json={"title": title},
                timeout=20,
            )
            data = resp.json()
            if data.get("code") != 0:
                print(f"  ❌ 飞书文档创建失败: {data.get('msg')} (代码: {data.get('code')})")
                return None

            doc_id = data["data"]["document"]["document_id"]
            # 使用通用域名确保手机端兼容性
            doc_url = f"https://www.feishu.cn/docx/{doc_id}"

            # 2. 将 Markdown 深度解析为飞书 Block
            lines = markdown_content.strip().split("\n")
            children = []
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
                    # 处理加粗格式 (**text**)
                    elements = []
                    parts = stripped.split("**")
                    for i, part in enumerate(parts):
                        if not part: continue
                        if i % 2 == 1:
                            elements.append({"text_run": {"content": part, "text_element_style": {"bold": True}}})
                        else:
                            elements.append({"text_run": {"content": part}})
                    if elements:
                        children.append({"block_type": 2, "text": {"elements": elements, "style": {}}})
                    else:
                        children.append({"block_type": 2, "text": {"elements": [{"text_run": {"content": stripped}}], "style": {}}})

            # 3. 分批写入内容 (飞书单次限制 50 blocks)
            batch_size = 50
            for i in range(0, len(children), batch_size):
                try:
                    batch_resp = client.post(
                        f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                        json={"children": children[i : i + batch_size]}, 
                        timeout=30
                    )
                    if batch_resp.json().get("code") != 0:
                        print(f"  ⚠️  文档内容写入异常 (Batch {i//batch_size + 1}): {batch_resp.json().get('msg')}")
                except Exception as e:
                    print(f"  ⚠️  文档内容网络传输异常 (Batch {i//batch_size + 1}): {e}")

            return doc_url
    except Exception as e:
        print(f"  ⚠️  飞书完整流程异常: {e}")
        return None


# ===== AI 处理 =====

def translate_and_summarize(tweets: list[dict]) -> str:
    """使用 AI 分批翻译并总结推文"""
    if not tweets: return ""

    # 每批处理的推文数量，避免超出 TPM 限制
    CHUNK_SIZE = 40
    chunks = [tweets[i : i + CHUNK_SIZE] for i in range(0, len(tweets), CHUNK_SIZE)]
    
    all_summaries = []
    
    for idx, chunk in enumerate(chunks):
        tweet_texts = []
        for t in chunk:
            prefix = f"@{t['username']} ({t['created_at']})"
            if t.get("is_retweet"): prefix += " [转发]"
            content = t["text"]
            tweet_texts.append(f"{prefix}:\n{content}")

        input_text = "\n\n".join(tweet_texts)
        print(f"🤖 AI 翻译总结中 (第 {idx+1}/{len(chunks)} 批, 处理 {len(chunk)} 条推文)...")

        try:
            response = groq_client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "moonshotai/kimi-k2-instruct-0905"),
                messages=[
                    {"role": "system", "content": SUMMARY_PROMPT},
                    {"role": "user", "content": input_text},
                ],
                temperature=0.3,
            )
            all_summaries.append(response.choices[0].message.content)
            
            # 如果有多批，稍微停顿一下避免触发每分钟调用频率限制
            if len(chunks) > 1 and idx < len(chunks) - 1:
                import time
                time.sleep(2)
                
        except Exception as e:
            print(f"⚠️  第 {idx+1} 批 AI 处理失败: {e}")
            all_summaries.append(f"\n[错误：本批次 {len(chunk)} 条推文处理失败]\n")

    return "\n\n---\n\n".join(all_summaries)


def generate_highlights(summary: str) -> str:
    """从总结中提取亮点摘要"""
    print("🤖 生成亮点摘要...")
    response = groq_client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "moonshotai/kimi-k2-instruct-0905"),
        messages=[
            {"role": "system", "content": "你是一位科技资讯编辑。请从以下日报中提取 5 条最重要的亮点，每条一句话，用 emoji 开头。只输出亮点列表，不要其他内容。"},
            {"role": "user", "content": summary},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content


# ===== 输出 =====

def save_output(content: str, tweet_count: int) -> Path:
    date = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M")
    output_path = OUTPUT_DIR / f"{date}-{time_str}.md"
    full_content = f"# X 科技摘要 · {date}\n\n生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n数据来源：{tweet_count} 条新推文\n\n---\n\n{content}"
    output_path.write_text(full_content, encoding="utf-8")
    print(f"💾 已保存：{output_path}")
    return output_path


# ===== 主函数 =====

def main():
    print("🚀 X-Digest 启动 (增量模式)\n")

    # 1. 加载所有账号并根据日期切分
    from config import ACCOUNTS
    
    # 获取当前是一年中的第几天，用于三日轮询
    day_index = datetime.now().timetuple().tm_yday % 3
    
    # 切分账号列表 (每份约 1/3)
    current_accounts = [acc for i, acc in enumerate(ACCOUNTS) if i % 3 == day_index]
    
    print(f"📅 今日轮询索引: {day_index}/2 (基于一年中的第 {datetime.now().timetuple().tm_yday} 天)")
    print(f"👥 账号分配: 本次抓取 {len(current_accounts)} 个账号，总计 {len(ACCOUNTS)} 个")

    # 2. 加载缓存
    cache = load_cache()
    print(f"📦 已加载缓存，包含 {len(cache)} 条记录")

    # 根据扫描记录过滤已成功的账号 (断点续传)
    resumable_accounts = []
    for acc in current_accounts:
        scan_key = f"SCAN_{acc}"
        if scan_key in cache:
            try:
                last_scan = datetime.fromisoformat(cache[scan_key])
                # 如果在过去 4 小时内已成功扫描过该账号，就跳过
                if datetime.now(timezone.utc) - last_scan < timedelta(hours=4):
                    print(f"⏩ 跳过最近已抓取的账号: @{acc}")
                    continue
            except: pass
        resumable_accounts.append(acc)
    
    current_accounts = resumable_accounts
    print(f"👥 待处理账号: 本次实际抓取 {len(current_accounts)} 个账号")

    # 定义实时更新缓存的回调
    def on_fetch_success(username, tweets_found):
        # 将新抓到的推文 ID 立即存入缓存并保存文件
        now_iso = datetime.now(timezone.utc).isoformat()
        # 1. 记录推文
        for t in tweets_found:
            if t["tweet_id"] not in cache:
                cache[t["tweet_id"]] = now_iso
        # 2. 标记账号扫描成功 (即使是0条)
        cache[f"SCAN_{username}"] = now_iso
        
        save_cache(clean_cache(cache))
        print(f"  💾 已实时保存缓存 (@{username})")

    # 3. 抓取推文 (传入筛选后的账号列表及成功回调)
    all_tweets = asyncio.run(fetch_all_tweets(
        accounts_list=current_accounts, 
        on_success=on_fetch_success
    ))
    
    # 4. 过滤已处理推文
    # 实际上，上面的逻辑更简单：直接用 all_tweets 即可，因为它们都是刚刚抓到的新推文。
    new_tweets = all_tweets 
    
    print(f"\n📊 抓取结果: 总计 {len(all_tweets)} 条 | 新推文 {len(new_tweets)} 条\n")

    if not new_tweets:
        print("✅ 没有发现新推文，无需总结。")
        save_cache(clean_cache(cache))
        return

    # 4. AI 翻译总结 (仅针对新推文)
    summary = translate_and_summarize(new_tweets)

    # 5. 生成亮点摘要
    highlights = generate_highlights(summary)

    # 6. 保存本地文件
    save_output(summary, len(new_tweets))

    # 7. 创建飞书文档
    date = datetime.now().strftime("%Y-%m-%d")
    doc_url = create_feishu_doc(f"X 科技摘要 · {date}", summary)

    # 8. 发飞书消息
    date_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"📰 X 科技摘要 · {date_time}\n\n🔥 今日亮点：\n{highlights}\n\n📄 完整报告：{doc_url if doc_url else '见本地 output/'}"
    send_feishu_message(msg)

    # 9. 最终清理缓存
    save_cache(clean_cache(cache))
    print("\n✅ 任务完成，已推送到飞书。")


if __name__ == "__main__":
    main()
