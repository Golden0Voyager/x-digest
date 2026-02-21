"""
使用 Twikit + 浏览器 Cookies 抓取推文
"""

import asyncio
import json
import os
from pathlib import Path
from datetime import datetime

from twikit import Client
from dotenv import load_dotenv

from config import ACCOUNTS, TWEETS_PER_ACCOUNT

load_dotenv()

PROXY = "http://127.0.0.1:8118"
COOKIES_FILE = "cookies.json"
BROWSER_COOKIES_FILE = "browser_cookies.json"


def convert_browser_cookies(browser_file: str, output_file: str):
    """将浏览器导出的 cookies 转换为 Twikit 格式（Netscape/httpx 格式）"""
    with open(browser_file, "r") as f:
        browser_cookies = json.load(f)

    # Twikit 使用 httpx，需要简单的 name=value 字典
    cookies = {}
    for cookie in browser_cookies:
        cookies[cookie["name"]] = cookie["value"]

    with open(output_file, "w") as f:
        json.dump(cookies, f, indent=2)

    print(f"✅ 已转换 {len(cookies)} 个 cookies → {output_file}")
    return cookies


async def fetch_user_tweets(client: Client, username: str) -> list[dict]:
    """获取指定用户的最新推文"""
    print(f"📥 抓取 @{username} ...")

    try:
        user = await client.get_user_by_screen_name(username)
        if not user:
            print(f"  ⚠️  未找到用户 @{username}")
            return []

        tweets = await client.get_user_tweets(user.id, "Tweets", count=TWEETS_PER_ACCOUNT)

        result = []
        for tweet in tweets:
            result.append({
                "username": username,
                "text": tweet.text,
                "created_at": tweet.created_at or "",
                "likes": tweet.favorite_count or 0,
                "retweets": tweet.retweet_count or 0,
            })
            text_preview = tweet.text[:60].replace('\n', ' ')
            print(f"  ✓ {text_preview}...")

        return result

    except Exception as e:
        print(f"  ❌ 抓取 @{username} 失败: {e}")
        return []


async def fetch_all_tweets() -> list[dict]:
    """抓取所有账号的推文"""
    client = Client("en-US", proxy=PROXY)

    # 转换并加载浏览器 cookies
    if not Path(COOKIES_FILE).exists():
        if Path(BROWSER_COOKIES_FILE).exists():
            convert_browser_cookies(BROWSER_COOKIES_FILE, COOKIES_FILE)
        else:
            raise FileNotFoundError(
                "请先导出浏览器 cookies 到 browser_cookies.json"
            )

    print("🔑 使用浏览器 cookies 登录...")
    client.load_cookies(COOKIES_FILE)
    print("✅ Cookies 加载成功\n")

    all_tweets = []
    for username in ACCOUNTS:
        tweets = await fetch_user_tweets(client, username)
        all_tweets.extend(tweets)
        # 避免请求过快
        await asyncio.sleep(2)

    return all_tweets


if __name__ == "__main__":
    tweets = asyncio.run(fetch_all_tweets())
    print(f"\n📊 共抓取 {len(tweets)} 条推文")
