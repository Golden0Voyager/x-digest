"""
使用 Playwright 浏览器抓取 Twitter 推文 - 极致隐身修复版
"""

import asyncio
import json
import os
import random
import hashlib
from datetime import datetime, timezone, timedelta

from playwright_stealth import Stealth
from playwright.async_api import async_playwright
from dotenv import load_dotenv

from config import ACCOUNTS, TWEETS_PER_ACCOUNT, HOURS_LOOKBACK

load_dotenv()

PROXY = os.getenv("PROXY", "http://127.0.0.1:8118")
BROWSER_COOKIES_FILE = "browser_cookies.json"

def load_browser_cookies() -> list[dict]:
    if not os.path.exists(BROWSER_COOKIES_FILE):
        return []
    with open(BROWSER_COOKIES_FILE) as f:
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

async def scrape_user_tweets(context, username: str) -> list[dict] | None:
    """抓取指定用户的推文（单次尝试）"""
    page = await context.new_page()
    try:
        # 直接调用单次抓取逻辑
        result = await _scrape_user_page(page, username)
        return result
    finally:
        await page.close()

async def _scrape_user_page(page, username: str) -> list[dict] | None:
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
                            tweet = {
                                "tweet_id": obj["rest_id"],
                                "text": legacy.get("full_text", ""),
                                "datetime_raw": legacy.get("created_at", ""),
                                "is_retweet": "retweeted_status_result" in obj.get("core", {}) or "retweeted_status_id_str" in legacy,
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

    # 2. 精简资源拦截 (保留更多以降低检测率)
    def should_abort(request):
        # 只拦截大型媒体资源，保留样式、字体和脚本以模拟真实渲染
        if request.resource_type in ["media", "image", "video"]: return True
        # 拦截明显的第三方追踪
        url = request.url.lower()
        if any(k in url for k in ["google-analytics", "doubleclick", "scribe.twitter.com"]): return True
        return False

    await page.route("**/*", lambda route: route.abort() if should_abort(route.request) else route.continue_())

    try:
        # 3. 访问前随机停顿
        await asyncio.sleep(random.uniform(2, 4))

        # 核心优化：改用 domcontentloaded 并在超时后不立即报错
        # 这样即使页面没完全加载（如图片慢），只要 API 数据回来了我们就能拿
        try:
            await page.goto(f"https://x.com/{username}", wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            if "Timeout" in str(e):
                print(f"  ⏳ 页面加载缓慢，尝试从已拦截数据中提取...")
            else:
                raise e

        cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_LOOKBACK)
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
                            "images": [], "likes": 0, "retweets": 0,
                        })
                    except: continue
                
                if result:
                    print(f"  ✓ 成功抓取 {len(result)} 条推文")
                    return result[:TWEETS_PER_ACCOUNT]

            # B. 智能识别并处理“屏蔽”或“刷新”页面
            body_text = await page.evaluate("document.body ? document.body.innerText : ''")
            if body_text and any(kw in body_text for kw in ["Retry", "Something went wrong", "出错了", "重新加载", "Try searching for something else"]):
                # 尝试原地点击“重试”按钮或刷新
                print(f"  ⚠️  命中 X 错误页，尝试原地刷新...")
                await page.reload(wait_until="load", timeout=30000)
                await asyncio.sleep(5)
                # 如果刷新一次还不行，才返回 None 触发外部大重试
                body_text_after = await page.evaluate("document.body ? document.body.innerText : ''")
                if any(kw in body_text_after for kw in ["Retry", "Something went wrong", "出错了"]):
                    return None

            # C. 模拟真实浏览行为
            await page.mouse.move(random.randint(100, 600), random.randint(100, 600))
            await page.evaluate(f"window.scrollBy(0, {random.randint(300, 700)})")
            await asyncio.sleep(random.uniform(3, 5))

        print(f"  ⚠️  超时未截获数据包")
        return None

    except Exception as e:
        print(f"  ❌ 抓取 @{username} 失败：{e}")
        return None

async def fetch_all_tweets(accounts_list=None, on_success=None) -> list[dict]:
    if accounts_list is None: accounts_list = ACCOUNTS
    cookies = load_browser_cookies()

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(
            headless=True,
            proxy={"server": PROXY},
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="UTC",
            color_scheme='dark',
        )
        await context.add_cookies(cookies)

        # 恢复单并发模式，牺牲速度换取稳定性
        semaphore = asyncio.Semaphore(1)
        all_tweets = []
        failed_accounts = []
        lock = asyncio.Lock()

        async def fetch_one(username, is_retry=False):
            async with semaphore:
                # 随机等待，防止请求过密 (5-10s)
                wait_time = random.uniform(5.0, 10.0) if not is_retry else random.uniform(10.0, 20.0)
                await asyncio.sleep(wait_time)

                if is_retry:
                    print(f"🔄 [重试阶段] 正在尝试抓取 @{username} ...")

                tweets = await scrape_user_tweets(context, username)

                if tweets is not None:  # 只有不是 None 才是真正扫描成功了
                    async with lock:
                        all_tweets.extend(tweets)

                    # 触发回调，记录“已扫”标记和抓到的推文
                    if on_success:
                        try:
                            if asyncio.iscoroutinefunction(on_success):
                                await on_success(username, tweets)
                            else:
                                on_success(username, tweets)
                        except Exception as e:
                            print(f"  ⚠️  执行回调失败: {e}")
                else:
                    # 记录失败
                    if not is_retry:
                        print(f"  ⚠️  @{username} 抓取失败，已加入稍后重试列表")
                        async with lock:
                            failed_accounts.append(username)
                    else:
                        print(f"  ❌ @{username} 重试依然失败 (本次跳过记录)")

        # --- 第一轮扫描 ---
        print(f"\n📊 [第一轮] 开始扫描 {len(accounts_list)} 个账号...")
        await asyncio.gather(*[fetch_one(u) for u in accounts_list])

        # --- 第二轮统一重试 ---
        if failed_accounts:
            retry_count = len(failed_accounts)
            print(f"\n⏳ [等待重试] 20秒后统一重试 {retry_count} 个失败账号...")
            await asyncio.sleep(20)
            print(f"🚀 [第二轮] 开始重试扫描 {retry_count} 个账号...")
            # 第二轮重试建议降低并发，更加温和
            semaphore = asyncio.Semaphore(1)
            await asyncio.gather(*[fetch_one(u, is_retry=True) for u in failed_accounts])

        await browser.close()

    return all_tweets

if __name__ == "__main__":
    tweets = asyncio.run(fetch_all_tweets())
    print(f"\n📊 共抓取 {len(tweets)} 条推文")
