"""
X (Twitter) 摘要生成器 - 主程序 (支持增量抓取、推文池合并与手动模式)

功能：抓取推文 → 入库合并 → 过滤 72h 推文 → 翻译汇总 → 输出 → 飞书推送
"""

import os
import asyncio
import json
import time
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from openai import OpenAI
from dotenv import load_dotenv

from config import SUMMARY_PROMPT, HOURS_LOOKBACK, ACCOUNT_SCAN_INTERVAL, AI_BATCH_SIZE
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

# 缓存文件 (仅用于记录扫描状态和重复过滤)
CACHE_FILE = OUTPUT_DIR / "processed_tweets.json"
# 推文池文件 (存储原始数据用于多日合并)
TWEET_POOL_FILE = OUTPUT_DIR / "raw_tweets_pool.json"

# 飞书配置
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
    """清理过旧的 ID 缓存和扫描记录"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    new_cache = {}
    for tid, ts_str in cache.items():
        try:
            if tid.startswith("SCAN_"):
                # 扫描记录如果超过 12 小时自动清除
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
    """从推文池中移除过期的推文"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    new_pool = {}
    for tid, tweet in pool.items():
        try:
            # 兼容处理推文中的创建时间
            ts = datetime.fromisoformat(tweet["created_at"])
            if ts > cutoff:
                new_pool[tid] = tweet
        except: continue
    return new_pool


# ===== 飞书 API =====

def get_feishu_token() -> str:
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
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_ID]):
        print("⚠️  飞书配置不完整，跳过推送")
        return
    try:
        token = get_feishu_token()
        if content is None: content = {"text": text}
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
            if resp.json().get("code") == 0:
                print("📨 飞书消息推送成功！")
    except Exception as e:
        print(f"⚠️  飞书发送异常: {e}")

def create_feishu_doc(title: str, markdown_content: str) -> str | None:
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET]): return None
    try:
        token = get_feishu_token()
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(trust_env=False, headers=headers) as client:
            resp = client.post("https://open.feishu.cn/open-apis/docx/v1/documents", json={"title": title}, timeout=20)
            data = resp.json()
            if data.get("code") != 0: return None
            doc_id = data["data"]["document"]["document_id"]
            doc_url = f"https://www.feishu.cn/docx/{doc_id}"
            
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
                    elements = []
                    parts = stripped.split("**")
                    for i, part in enumerate(parts):
                        if not part: continue
                        if i % 2 == 1:
                            elements.append({"text_run": {"content": part, "text_element_style": {"bold": True}}})
                        else:
                            elements.append({"text_run": {"content": part}})
                    children.append({"block_type": 2, "text": {"elements": elements if elements else [{"text_run": {"content": stripped}}], "style": {}}})

            batch_size = 50
            for i in range(0, len(children), batch_size):
                client.post(f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", json={"children": children[i : i + batch_size]}, timeout=30)
            return doc_url
    except Exception as e:
        print(f"  ⚠️  飞书文档流程异常: {e}")
        return None


# ===== AI 处理 =====

def translate_and_summarize(tweets: list[dict]) -> str:
    """使用 AI 对每条推文进行编译 (精简三要素版)"""
    if not tweets: return ""
    
    # 1. 确保全量推文按时间倒序排列
    tweets.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    # 2. 分批进行编译处理
    CHUNK_SIZE = AI_BATCH_SIZE
    chunks = [tweets[i : i + CHUNK_SIZE] for i in range(0, len(tweets), CHUNK_SIZE)]
    
    all_raw_items_list = []
    
    # 极简三要素提示词 (Token 优化版)
    COMPILE_PROMPT = """
    你是一位专业的科技编译。请将以下 Twitter 资讯编译为极简条目。
    
    要求：
    1. **三要素原则**：
       - 原文：保留 100% 完整英文/原始文本。
       - 译文：仅当原文非中文时翻译；若原文已是中文，此项填 "SKIP"。
       - 启示：用 1-2 句话点出该消息的深层价值或潜在启发。
    2. **分类**：【核心头条】、【AI & 算法】、【芯片 & 硬件】、【航天 & 自动驾驶】、【市场 & 投资】、【政治 & 政策】。
    3. 每个条目严格以 "---ITEM_START---" 开始，以 "---ITEM_END---" 结束。
    
    输出模板：
    ---ITEM_START---
    CAT: [分类名]
    ID: [直接填入我提供的 ID]
    ORIGINAL: [完整原文]
    TRANSLATION: [译文内容 或 SKIP]
    THOUGHT: 💡 **启示**：[启发式思考内容]
    ---ITEM_END---
    """

    for idx, chunk in enumerate(chunks):
        tweet_texts = []
        for t in chunk:
            # 仅向 AI 发送 ID 和内容，不发送完整 URL 以节省 Token
            tweet_texts.append(f"ID: {t['tweet_id']}\nUSER: @{t['username']}\nTEXT: {t['text']}")

        input_text = "\n\n".join(tweet_texts)
        print(f"🤖 正在编译精简条目 (第 {idx+1}/{len(chunks)} 批)...")

        try:
            response = groq_client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "moonshotai/kimi-k2-instruct-0905"),
                messages=[{"role": "system", "content": COMPILE_PROMPT}, {"role": "user", "content": input_text}],
                temperature=0.2,
            )
            content = response.choices[0].message.content
            items = content.split("---ITEM_START---")
            for item in items:
                if "---ITEM_END---" in item:
                    clean_item = item.split("---ITEM_END---")[0].strip()
                    if clean_item: all_raw_items_list.append(clean_item)
            if len(chunks) > 1: time.sleep(2)
        except Exception as e:
            print(f"⚠️  第 {idx+1} 批编译失败: {e}")

    # 3. 生成全局趋势总结
    summary_context = "\n\n".join(all_raw_items_list[:50])
    try:
        trend_resp = groq_client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "moonshotai/kimi-k2-instruct-0905"),
            messages=[
                {"role": "system", "content": "你是一位资深科技主编。基于以下资讯撰写 200 字「🛰️ 今日全球科技脉动」。要求总结趋势、地缘关联及情绪。"},
                {"role": "user", "content": summary_context},
            ],
            temperature=0.3,
        )
        global_trend = trend_resp.choices[0].message.content
    except:
        global_trend = "（趋势总结生成失败）"

    # 4. 本地精美组装
    from config import ACCOUNTS
    import re
    
    display_categories = [
        ("【核心头条】", ["核心头条", "核心"]),
        ("【AI & 算法】", ["AI", "算法"]),
        ("【芯片 & 硬件】", ["芯片", "硬件"]),
        ("【航天 & 自动驾驶】", ["航天", "自动驾驶"]),
        ("【市场 & 投资】", ["市场", "投资"]),
        ("【政治 & 政策】", ["政治", "政策"]),
    ]
    
    category_items = {name: [] for name, _ in display_categories}
    fallback_items = []

    # 预先构建一个 ID 到 用户名 的映射表，用于本地还原 URL
    id_to_user = {str(t["tweet_id"]): t["username"] for t in tweets}

    for item in all_raw_items_list:
        lines = item.split("\n")
        data = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                data[k.strip()] = v.strip()
        
        # 提取核心要素
        tid = data.get("ID", "")
        original = data.get("ORIGINAL", "")
        translation = data.get("TRANSLATION", "")
        thought = data.get("THOUGHT", "")
        cat_val = data.get("CAT", "")
        
        # 1. 清洗原推文：剔除推文末尾可能存在的 t.co 链接（通常是图片/视频占位符）
        original = re.sub(r'https://t\.co/[a-zA-Z0-9]+$', '', original).strip()
        
        # 2. 本地还原 URL
        username = id_to_user.get(tid, "Unknown")
        url = f"https://x.com/{username}/status/{tid}" if tid != "Unknown" else "#"
        bio = ACCOUNTS.get(username, "博主信息暂无")

        # 3. 统一思考模块标签
        thought = thought.replace("💡 **启示**：", "💡 **深度启示**：")

        # 4. 格式化单个条目 (链接紧跟在原文正文后方，保持绝对精简)
        entry = f"**@{username}** ({bio})\n"
        entry += f"> {original} [[🔗]({url})]\n\n"
        if translation.upper() != "SKIP" and translation:
            entry += f"📝 **译文**：{translation}\n\n"
        entry += f"{thought}"

        # 分类归档
        matched = False
        for section_name, keywords in display_categories:
            if any(kw in cat_val for kw in keywords):
                category_items[section_name].append(entry)
                matched = True
                break
        if not matched: fallback_items.append(entry)

    # 5. 拼装最终 Markdown
    final_report = [f"{global_trend}\n\n---\n"]
    for section_name, _ in display_categories:
        items = category_items[section_name]
        if items:
            final_report.append(f"### {section_name}")
            final_report.append("\n\n---\n\n".join(items))
            final_report.append("\n")
    
    if fallback_items:
        final_report.append("### 【其他动态】")
        final_report.append("\n\n---\n\n".join(fallback_items))

    return "\n\n".join(final_report)

def generate_highlights(summary: str) -> str:
    print("🤖 生成亮点摘要...")
    try:
        response = groq_client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "moonshotai/kimi-k2-instruct-0905"),
            messages=[
                {"role": "system", "content": "你是一位科技资讯编辑。请从以下日报中提取 5 条最重要的亮点，每条一句话，用 emoji 开头。只输出亮点列表，不要其他内容。"},
                {"role": "user", "content": summary},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"⚠️  生成亮点失败: {e}")
        return "亮点提取失败"


import markdown

# ... (other imports)

async def render_markdown_to_pdf(md_path: Path):
    """利用 Playwright 将 Markdown 转换为精美 PDF"""
    try:
        from playwright.async_api import async_playwright
        import markdown
        
        pdf_path = md_path.with_suffix(".pdf")
        md_content = md_path.read_text(encoding="utf-8")
        
        # 转换 Markdown 为 HTML (带基础排版样式)
        html_body = markdown.markdown(md_content, extensions=['extra', 'codehilite', 'toc'])
        
        # 构建一个带美观样式的完整 HTML 页面 (Google Material / 极简主义)
        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 900px;
                    margin: 0 auto;
                    padding: 40px;
                    background-color: #fff;
                }}
                h1 {{ color: #1a73e8; border-bottom: 2px solid #e8eaed; padding-bottom: 10px; }}
                h2 {{ color: #202124; margin-top: 30px; border-left: 5px solid #1a73e8; padding-left: 15px; }}
                blockquote {{
                    background: #f8f9fa;
                    border-left: 10px solid #ccc;
                    margin: 1.5em 10px;
                    padding: 0.5em 10px;
                    quotes: "\\201C""\\201D""\\2018""\\2019";
                    color: #555;
                    font-style: italic;
                }}
                hr {{ border: 0; height: 1px; background: #e8eaed; margin: 20px 0; }}
                strong {{ color: #1a73e8; }}
                code {{ background-color: #f1f3f4; padding: 2px 4px; border-radius: 4px; font-family: monospace; }}
            </style>
        </head>
        <body>
            {html_body}
        </body>
        </html>
        """
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(full_html)
            # 等待渲染完成
            await page.wait_for_timeout(1000)
            await page.pdf(
                path=str(pdf_path),
                format="A4",
                margin={"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"},
                print_background=True
            )
            await browser.close()
            print(f"📄 已同步生成 PDF：{pdf_path}")
            return pdf_path
    except Exception as e:
        print(f"⚠️  PDF 生成失败: {e}")
        return None

# ===== 输出 =====

def save_output(content: str, tweet_count: int, hours: int) -> Path:
    date = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M")
    output_path = OUTPUT_DIR / f"{date}-{time_str}.md"
    
    # 增强页眉排版
    header = f"""# 🛰️ X-Digest 科技汇总日报
> **📅 生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> **📊 汇总窗口**：过去 {hours} 小时全量大合拢
> **📡 数据来源**：{tweet_count} 条有效推文 (中英对照版)

---

"""
    full_content = header + content
    output_path.write_text(full_content, encoding="utf-8")
    print(f"💾 已保存精美排版报告：{output_path}")
    return output_path


# ===== 主函数 =====

def main():
    parser = argparse.ArgumentParser(description="X-Digest 推文摘要生成器")
    parser.add_argument("--manual", action="store_true", help="手动模式：扫描所有账号")
    parser.add_argument("--hours", type=int, default=None, help=f"回溯小时数 (默认 {HOURS_LOOKBACK})")
    parser.add_argument("--force", action="store_true", help="强制模式：忽略冷却时间")
    parser.add_argument("--batch", type=int, choices=[1, 2, 3], help="指定账号批次")
    args = parser.parse_args()

    # 智能交互菜单
    if not any([args.manual, args.hours is not None, args.force, args.batch is not None]):
        print("\n🚀 X-Digest 启动控制台")
        prompt = "选择模式: [A]自动(默认) | [F]全量 | [1/2/3]批次 | [C]自定义 : "
        choice = input(prompt).strip().upper()

        if choice == "F":
            args.manual = True
        elif choice in ["1", "2", "3"]:
            args.batch = int(choice)
        elif choice == "C":
            # 进入自定义流
            print("\n--- 自定义配置 ---")
            scope = input("账号范围 ([A]全量 | [1/2/3]批次 | [Enter]自动): ").strip().upper()
            if scope == "A": args.manual = True
            elif scope in ["1", "2", "3"]: args.batch = int(scope)
            
            h = input(f"回溯时长 (小时, 默认 {HOURS_LOOKBACK}): ").strip()
            if h: args.hours = int(h)
            
            f = input("强制重扫? (y/N): ").strip().lower()
            if f == "y": args.force = True
        # 其他或回车默认为 Auto (保持默认参数)

    # 设置默认时长
    if args.hours is None: args.hours = HOURS_LOOKBACK

    print(f"\n✨ 模式确认: {'全量' if args.manual else (f'第 {args.batch} 批次' if args.batch else '自动轮询')} | {args.hours}h 回溯")

    # 1. 加载配置与数据
    from config import ACCOUNTS
    # 获取账号名列表
    all_account_names = list(ACCOUNTS.keys())
    
    cache = load_json(CACHE_FILE)
    pool = load_json(TWEET_POOL_FILE)
    print(f"📦 已加载缓存 ({len(cache)} 条记录) 和推文池 ({len(pool)} 条数据)")

    # 2. 账号分配
    if args.manual:
        current_accounts = all_account_names
        print(f"👤 手动全量模式：扫描 {len(current_accounts)} 个账号")
    else:
        # 确定批次索引 (0, 1, 2)
        if args.batch:
            day_index = args.batch - 1
            print(f"🎯 指定批次模式: 强制选择第 {args.batch}/3 组账号")
        else:
            day_index = datetime.now().timetuple().tm_yday % 3
            print(f"📅 自动轮询模式 (索引: {day_index}/2): 基于一年中的第 {datetime.now().timetuple().tm_yday} 天")
            
        current_accounts = [acc for i, acc in enumerate(all_account_names) if i % 3 == day_index]
        print(f"👥 分配账号: 本次处理 {len(current_accounts)}/{len(all_account_names)} 个账号")

    # 3. 过滤最近已处理的账号
    if not args.force:
        active_accounts = []
        for acc in current_accounts:
            scan_key = f"SCAN_{acc}"
            if scan_key in cache:
                try:
                    last_scan = datetime.fromisoformat(cache[scan_key])
                    if datetime.now(timezone.utc) - last_scan < timedelta(hours=ACCOUNT_SCAN_INTERVAL):
                        print(f"⏩ 跳过最近已抓取的账号: @{acc}")
                        continue
                except: pass
            active_accounts.append(acc)
        current_accounts = active_accounts

    # 定义抓取成功后的实时同步回调
    def on_fetch_success(username, tweets_found):
        now_iso = datetime.now(timezone.utc).isoformat()
        # 更新 ID 缓存和扫描记录
        cache[f"SCAN_{username}"] = now_iso
        for t in tweets_found:
            if t["tweet_id"] not in cache:
                cache[t["tweet_id"]] = now_iso
            # 同步更新原始推文池
            pool[t["tweet_id"]] = t
        
        # 实时保存，防止中断丢失数据
        save_json(CACHE_FILE, clean_cache(cache, args.hours))
        save_json(TWEET_POOL_FILE, clean_pool(pool, args.hours))

    # 4. 执行抓取
    print(f"\n📡 开始抓取 {len(current_accounts)} 个账号的最新推文...")
    asyncio.run(fetch_all_tweets(
        accounts_list=current_accounts, 
        on_success=on_fetch_success,
        hours_lookback=args.hours
    ))

    # 5. 从推文池提取 72h (或自定义小时) 的推文进行汇总
    pool = clean_pool(pool, args.hours) # 最终清理
    save_json(TWEET_POOL_FILE, pool)
    
    selected_tweets = list(pool.values())
    print(f"\n📊 汇总结果: 推文池中共计 {len(selected_tweets)} 条推文符合 {args.hours}h 回溯要求")

    if not selected_tweets:
        print("✅ 池中无符合条件的推文，任务结束。")
        return

    # 6. AI 翻译总结全量数据
    summary = translate_and_summarize(selected_tweets)
    highlights = generate_highlights(summary)

    # 7. 保存与推送
    output_path = save_output(summary, len(selected_tweets), args.hours)
    
    # 7.1 同步生成 PDF
    asyncio.run(render_markdown_to_pdf(output_path))
    
    date_label = datetime.now().strftime("%Y-%m-%d")
    doc_url = create_feishu_doc(f"X 科技汇总 ({args.hours}h) · {date_label}", summary)

    date_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"📰 X 科技汇总报告 ({args.hours}h回溯)\n\n🔥 核心亮点：\n{highlights}\n\n📄 完整报告：{doc_url if doc_url else '见本地 output/'}\n📊 数据来源：{len(selected_tweets)} 条推文"
    send_feishu_message(msg)

    print("\n✅ 任务完成，已发布 72 小时大合拢汇总报告。")


if __name__ == "__main__":
    main()
