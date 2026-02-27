"""
使用 Playwright 浏览器抓取 Twitter 推文
"""

import asyncio
import json
import os
from datetime import datetime, timezone, timedelta

from playwright.async_api import async_playwright
from dotenv import load_dotenv

from config import ACCOUNTS, TWEETS_PER_ACCOUNT, HOURS_LOOKBACK

load_dotenv()

PROXY = os.getenv("PROXY", "http://127.0.0.1:8118")
BROWSER_COOKIES_FILE = "browser_cookies.json"


def load_browser_cookies() -> list[dict]:
    """加载浏览器导出的 cookies 并转换为 Playwright 格式"""
    import time as _time

    with open(BROWSER_COOKIES_FILE) as f:
        cookies = json.load(f)

    # 检查 cookie 文件新鲜度
    file_mtime = os.path.getmtime(BROWSER_COOKIES_FILE)
    age_hours = (_time.time() - file_mtime) / 3600
    if age_hours > 48:
        print(f"⚠️  Cookie 文件已 {age_hours:.0f} 小时未更新，建议重新导出！")

    pw_cookies = []
    for c in cookies:
        pc = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "secure": c.get("secure", True),
            "httpOnly": c.get("httpOnly", False),
        }
        if c.get("expirationDate"):
            pc["expires"] = c["expirationDate"]
        ss = c.get("sameSite")
        if ss == "no_restriction":
            pc["sameSite"] = "None"
        elif ss == "lax":
            pc["sameSite"] = "Lax"
        elif ss == "strict":
            pc["sameSite"] = "Strict"
        pw_cookies.append(pc)
    return pw_cookies


async def scrape_user_tweets(context, username: str, retries: int = 2) -> list[dict]:
    """抓取指定用户的推文（带重试）"""
    for attempt in range(retries + 1):
        page = await context.new_page()
        try:
            result = await _scrape_user_page(page, username)
            if result is not None:
                return result
            if attempt < retries:
                print(f"  🔄 重试 @{username} ({attempt + 1}/{retries})")
                await asyncio.sleep(3)
        finally:
            await page.close()
    return []


async def _scrape_user_page(page, username: str) -> list[dict] | None:
    """单次抓取尝试，返回 None 表示需要重试"""
    print(f"📥 抓取 @{username} ...")

    try:
        resp = await page.goto(
            f"https://x.com/{username}",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        # 检测登录/限流
        if resp and resp.status in (401, 403, 429):
            print(f"  ⚠️  HTTP {resp.status}，可能被限流或 cookie 失效")
            return None

        # 等待推文加载
        try:
            await page.wait_for_selector(
                'article[data-testid="tweet"]', timeout=15000
            )
        except Exception:
            print(f"  ⚠️  未找到推文，可能用户不存在或页面加载失败")
            return []

        # 滚动加载更多推文（多轮滚动，确保加载充分）
        prev_count = 0
        for i in range(8):
            await page.evaluate("window.scrollBy(0, 2000)")
            await page.wait_for_timeout(2000)
            cur_count = await page.evaluate(
                "document.querySelectorAll('article[data-testid=\"tweet\"]').length"
            )
            if cur_count == prev_count and i >= 3:
                break  # 没有新推文加载了
            prev_count = cur_count

        # 提取推文
        tweets_data = await page.evaluate("""() => {
            const tweets = [];
            document.querySelectorAll('article[data-testid="tweet"]').forEach(article => {
                try {
                    const textEl = article.querySelector('[data-testid="tweetText"]');
                    const text = textEl ? textEl.innerText : '';
                    const timeEl = article.querySelector('time');
                    const dt = timeEl ? timeEl.getAttribute('datetime') : '';
                    if (text && dt) {
                        tweets.push({ text, datetime: dt });
                    }
                } catch(e) {}
            });
            return tweets;
        }""")

        # 时间过滤 + 去重
        cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_LOOKBACK)
        seen = set()
        result = []

        for t in tweets_data:
            # 去重
            text_key = t["text"][:100]
            if text_key in seen:
                continue
            seen.add(text_key)

            # 时间过滤
            try:
                tweet_time = datetime.fromisoformat(
                    t["datetime"].replace("Z", "+00:00")
                )
                if tweet_time < cutoff:
                    continue
            except (ValueError, TypeError):
                continue

            result.append({
                "username": username,
                "text": t["text"],
                "created_at": t["datetime"],
                "likes": 0,
                "retweets": 0,
            })
            text_preview = t["text"][:60].replace("\n", " ")
            print(f"  ✓ {text_preview}...")

            if len(result) >= TWEETS_PER_ACCOUNT:
                break

        if not result:
            print(f"  ✓ 最近 {HOURS_LOOKBACK}h 无新推文")

        return result

    except Exception as e:
        print(f"  ❌ 抓取 @{username} 失败: {e}")
        return []


async def fetch_all_tweets() -> list[dict]:
    """抓取所有账号的推文（并发 + 重试）"""
    cookies = load_browser_cookies()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            proxy={"server": PROXY},
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        await context.add_cookies(cookies)

        # 并发抓取（3 个并发页面）
        semaphore = asyncio.Semaphore(3)
        all_tweets = []
        lock = asyncio.Lock()

        async def fetch_one(username):
            async with semaphore:
                tweets = await scrape_user_tweets(context, username)
                async with lock:
                    all_tweets.extend(tweets)
                await asyncio.sleep(1)

        await asyncio.gather(*[fetch_one(u) for u in ACCOUNTS])
        await browser.close()

    return all_tweets


if __name__ == "__main__":
    tweets = asyncio.run(fetch_all_tweets())
    print(f"\n📊 共抓取 {len(tweets)} 条推文")
