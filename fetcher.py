"""
使用 Playwright 浏览器抓取 Twitter 推文 - 极致隐身修复版
"""

import asyncio
import json
import os
import random
import hashlib
import glob
import re
import logging
from datetime import datetime, timezone, timedelta

from playwright_stealth import Stealth
from playwright.async_api import async_playwright
from dotenv import load_dotenv

from config import ACCOUNTS, TWEETS_PER_ACCOUNT, HOURS_LOOKBACK

load_dotenv()

# ANSI 色彩代码
class Color:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    GREY = "\033[90m"

# 获取与 main.py 共享的日志记录器
logger = logging.getLogger("x_digest")

def log_print(msg, level="info"):
    """辅助函数：同时向终端和日志文件输出"""
    # 剥离 ANSI 颜色代码后写入日志文件
    clean_msg = re.sub(r'\033\[\d+(;\d+)*m', '', str(msg))
    if level == "info":
        logger.info(clean_msg)
    elif level == "warning":
        logger.warning(clean_msg)
    elif level == "error":
        logger.error(clean_msg)
    print(msg)

PROXY = os.getenv("PROXY", "http://127.0.0.1:7897")
BROWSER_COOKIES_FILE = "browser_cookies.json"

def load_browser_cookies(file_path: str) -> list[dict]:
    if not os.path.exists(file_path):
        return []
    with open(file_path) as f:
        cookies = json.load(f)
    pw_cookies = []
    for c in cookies:
        pc = {
            "name": c["name"], "value": c["value"], "domain": c["domain"],
            "path": c.get("path", "/"), "secure": c.get("secure", True),
            "httpOnly": c.get("httpOnly", False),
        }
        if c.get("expirationDate"): pc["expires"] = c["expirationDate"]
        pw_cookies.append(pc)
    return pw_cookies

async def scrape_user_tweets(context, username: str, hours_lookback: int = HOURS_LOOKBACK) -> list[dict] | None:
    """抓取指定用户的推文（单次尝试）"""
    page = await context.new_page()
    try:
        # 直接调用单次抓取逻辑
        result = await _scrape_user_page(page, username, hours_lookback)
        return result
    finally:
        await page.close()

async def _scrape_user_page(page, username: str, hours_lookback: int = HOURS_LOOKBACK) -> list[dict] | None:
    """单次抓取尝试"""
    print(f"📥 抓取 @{username} ...")

    graphql_tweets = []

    # 1. 监听 GraphQL 响应 (最稳的数据来源)
    async def handle_response(response):
        if "UserTweets" in response.url or "UserByScreenName" in response.url:
            try:
                data = await response.json()
                def extract_tweets(obj):
                    if isinstance(obj, dict):
                        if obj.get("rest_id") and obj.get("legacy"):
                            legacy = obj["legacy"]
                            # 提取图片 URL
                            media_entities = legacy.get("extended_entities", {}).get("media", []) or legacy.get("entities", {}).get("media", [])
                            images = [m["media_url_https"] for m in media_entities if m.get("type") == "photo" and m.get("media_url_https")]
                            tweet = {
                                "tweet_id": obj["rest_id"],
                                "text": legacy.get("full_text", ""),
                                "datetime_raw": legacy.get("created_at", ""),
                                "is_retweet": "retweeted_status_result" in obj.get("core", {}) or "retweeted_status_id_str" in legacy,
                                "images": images,
                            }
                            try:
                                dt = datetime.strptime(tweet["datetime_raw"], "%a %b %d %H:%M:%S %z %Y")
                                tweet["datetime"] = dt.isoformat()
                            except: tweet["datetime"] = tweet["datetime_raw"]
                            graphql_tweets.append(tweet)
                        for v in obj.values(): extract_tweets(v)
                    elif isinstance(obj, list):
                        for item in obj: extract_tweets(item)
                extract_tweets(data)
            except: pass

    page.on("response", handle_response)

    # 2. 精简资源拦截
    def should_abort(request):
        if request.resource_type in ["media", "image", "video"]: return True
        url = request.url.lower()
        if any(k in url for k in ["google-analytics", "doubleclick", "scribe.twitter.com"]): return True
        return False

    await page.route("**/*", lambda route: route.abort() if should_abort(route.request) else route.continue_())

    try:
        # 3. 访问前随机停顿
        await asyncio.sleep(random.uniform(2, 4))

        # 核心优化：改用 domcontentloaded 并在超时后不立即报错
        # 这样即使页面没完全加载（如图片慢），只要 API 数据回来了我们就能拿
        for attempt in range(3):
            try:
                # 随机延迟避免过快重试被封
                if attempt > 0:
                    await asyncio.sleep(random.uniform(5, 10))
                await page.goto(f"https://x.com/{username}", wait_until="domcontentloaded", timeout=25000)
                break
            except Exception as e:
                if "Timeout" in str(e):
                    print(f"  ⏳ 页面加载缓慢 (尝试 {attempt+1}/3)，尝试从已拦截数据中提取...")
                    if attempt == 2:
                        break
                else:
                    if attempt == 2:
                        raise e
                    print(f"  ⚠️ 页面访问异常 (尝试 {attempt+1}/3): {e}，准备重试...")

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_lookback)
        start_time = asyncio.get_event_loop().time()

        # 增加一点初始等待，让数据有时间拦截
        await asyncio.sleep(5)

        # 截获窗口增加到 60 秒
        while (asyncio.get_event_loop().time() - start_time) < 60:
            # A. 检查 GraphQL 是否已经截获数据
            if graphql_tweets:
                result = []
                seen = set()
                for t in graphql_tweets:
                    uid = t.get("tweet_id") or hashlib.md5(t["text"].encode()).hexdigest()
                    if uid in seen: continue
                    seen.add(uid)
                    try:
                        tweet_time = datetime.fromisoformat(t["datetime"])
                        if tweet_time < cutoff: continue
                        result.append({
                            "tweet_id": uid, "username": username, "text": t["text"],
                            "is_retweet": t["is_retweet"], "created_at": t["datetime"],
                            "images": t.get("images", []), "likes": 0, "retweets": 0,
                        })
                    except: continue

                if result:
                    print(f"  ✓ 成功抓取 {len(result)} 条推文")
                    return result[:TWEETS_PER_ACCOUNT]
                else:
                    # 收到数据包但没有符合时间限制的内容，说明确实没发推
                    print(f"  ✓ @{username} 无符合 {hours_lookback}h 条件的推文")
                    return []

            # B. 智能识别并处理"屏蔽"或"刷新"页面
            body_text = await page.evaluate("document.body ? document.body.innerText : ''")
            if body_text and any(kw in body_text for kw in ["Retry", "Something went wrong", "出错了", "重新加载", "Try searching for something else"]):
                print(f"  ⚠️  命中 X 错误页，尝试原地刷新...")
                await page.reload(wait_until="load", timeout=30000)
                await asyncio.sleep(5)
                body_text_after = await page.evaluate("document.body ? document.body.innerText : ''")
                if any(kw in body_text_after for kw in ["Retry", "Something went wrong", "出错了"]):
                    return None

            # C. 模拟真实浏览行为
            await page.mouse.move(random.randint(100, 600), random.randint(100, 600))
            await page.evaluate(f"window.scrollBy(0, {random.randint(300, 700)})")

            await asyncio.sleep(random.uniform(2, 4))

            # 检查是否触底
            at_bottom = await page.evaluate("window.innerHeight + window.scrollY >= document.body.scrollHeight")
            if at_bottom and (asyncio.get_event_loop().time() - start_time) > 20:
                print(f"  ✓ @{username} 页面已触底，未发现更早内容")
                break

        if not graphql_tweets:
            print(f"  ⚠️  超时未截获数据包，可能页面已被限制")
            return None
        return []

    except Exception as e:
        print(f"  ❌ 抓取 @{username} 失败：{e}")
        return None

async def fetch_all_tweets(accounts_list=None, on_success=None, hours_lookback: int = HOURS_LOOKBACK) -> list[dict]:
    if accounts_list is None: accounts_list = ACCOUNTS

    cookie_files = sorted(glob.glob("browser_cookies*.json"))
    if not cookie_files:
        print("  ⚠️  未发现任何 browser_cookies*.json 文件")
        cookie_data_list = [[]]
    else:
        cookie_data_list = [load_browser_cookies(f) for f in cookie_files]

    num_contexts = len(cookie_data_list)
    print(f"  🔑 已加载 {num_contexts} 组 Cookie（{'双账号并发模式' if num_contexts >= 2 else '单账号模式'}）")

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True, proxy={"server": PROXY}, args=["--disable-blink-features=AutomationControlled"])

        contexts = []
        for i, cookies in enumerate(cookie_data_list):
            ctx = await browser.new_context(
                user_agent=f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/13{i}.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}, locale="en-US", timezone_id="UTC", color_scheme='dark',
            )
            if cookies: await ctx.add_cookies(cookies)
            contexts.append(ctx)

        # ===== 改动 1：会话预热 — 访问首页激活 cookie 会话 =====
        for i, ctx in enumerate(contexts):
            page = await ctx.new_page()
            try:
                await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(3)
                log_print(f"  ✓ Cookie #{i+1} 会话预热成功")
            except Exception as e:
                log_print(f"  ⚠️  Cookie #{i+1} 预热失败: {e}", "warning")
            finally:
                await page.close()

        all_tweets = []
        failed_accounts = []  # 记录 (username, 首轮所用 context_idx)
        lock = asyncio.Lock()

        # ===== 改动 2：Per-Context 队列 — 每个 context 独立串行队列，队列间并行 =====
        async def process_queue(context_idx: int, queue: list[str], is_retry=False):
            """单个 context 的串行处理队列"""
            ctx = contexts[context_idx]
            consecutive_failures = 0

            for username in queue:
                # 每次请求前保持合理间隔
                wait_time = random.uniform(5.0, 10.0) if not is_retry else random.uniform(10.0, 20.0)
                await asyncio.sleep(wait_time)

                # 连续失败降温
                if consecutive_failures >= 5:
                    log_print(f"  {Color.YELLOW}🛑 Context #{context_idx+1} 连续失败 5 次，IP 降温 (冷却 30s)...{Color.RESET}")
                    await asyncio.sleep(30)
                    consecutive_failures = 0

                if is_retry:
                    print(f"🔄 [重试·换号] 正在用 Cookie #{context_idx+1} 重试 @{username} ...")

                tweets = await scrape_user_tweets(ctx, username, hours_lookback)

                # 健康度回调（成功和失败都通知）
                if on_success:
                    try:
                        if asyncio.iscoroutinefunction(on_success): await on_success(username, tweets)
                        else: on_success(username, tweets)
                    except Exception as e: print(f"  ⚠️  回调执行失败: {e}")

                if tweets is not None:
                    consecutive_failures = 0
                    async with lock: all_tweets.extend(tweets)
                else:
                    consecutive_failures += 1
                    if not is_retry:
                        print(f"  ⚠️  @{username} 抓取失败，已加入稍后重试列表")
                        async with lock: failed_accounts.append((username, context_idx))
                    else:
                        print(f"  ❌ @{username} 重试依然失败 (本次跳过)")

        # 按 context 数量将账号分配到各队列（round-robin 分配）
        queues = [[] for _ in range(num_contexts)]
        for i, username in enumerate(accounts_list):
            queues[i % num_contexts].append(username)

        queue_info = " | ".join([f"队列{i+1}: {len(q)}人" for i, q in enumerate(queues)])
        print(f"\n📊 [第一轮] 开始扫描 {len(accounts_list)} 个账号（{queue_info}）...")

        # 所有队列并行启动
        await asyncio.gather(*[process_queue(i, q) for i, q in enumerate(queues)])

        # ===== 改动 3：跨 Cookie 重试 — 失败账号切换到另一个 context =====
        if failed_accounts:
            retry_count = len(failed_accounts)
            print(f"\n⏳ [等待重试] 20秒后统一重试 {retry_count} 个失败账号（切换 Cookie）...")
            await asyncio.sleep(20)

            # 将失败账号分配到与首轮不同的 context（跨号重试）
            retry_queues = [[] for _ in range(num_contexts)]
            for username, original_ctx_idx in failed_accounts:
                if num_contexts >= 2:
                    # 多 context：切换到另一个 context
                    new_ctx_idx = (original_ctx_idx + 1) % num_contexts
                else:
                    # 单 context：只能用同一个
                    new_ctx_idx = 0
                retry_queues[new_ctx_idx].append(username)

            retry_info = " | ".join([f"Cookie#{i+1}: {len(q)}人" for i, q in enumerate(retry_queues) if q])
            print(f"🚀 [第二轮] 跨号重试（{retry_info}）...")

            await asyncio.gather(*[
                process_queue(i, q, is_retry=True)
                for i, q in enumerate(retry_queues) if q
            ])

        for ctx in contexts: await ctx.close()
        await browser.close()

    return all_tweets
