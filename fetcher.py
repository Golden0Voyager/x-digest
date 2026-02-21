"""
使用 Twikit 抓取推文（无需 Twitter API Key）
需要 Twitter 账号登录
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

COOKIES_FILE = "cookies.json"


async def login(client: Client):
    """登录 Twitter 账号"""
    # 优先使用已保存的 cookies
    if Path(COOKIES_FILE).exists():
        print("🔑 使用已保存的 cookies 登录...")
        client.load_cookies(COOKIES_FILE)
        return

    # 首次登录
    username = os.getenv("TWITTER_USERNAME")
    email = os.getenv("TWITTER_EMAIL")
    password = os.getenv("TWITTER_PASSWORD")

    if not all([username, email, password]):
        raise ValueError(
            "首次登录需要设置 TWITTER_USERNAME, TWITTER_EMAIL, TWITTER_PASSWORD"
        )

    print(f"🔑 使用账号 @{username} 登录...")
    await client.login(
        auth_info_1=username,
        auth_info_2=email,
        password=password,
        cookies_file=COOKIES_FILE,
    )
    print("✅ 登录成功，cookies 已保存")


async def fetch_user_tweets(client: Client, username: str) -> list[dict]:
    """获取指定用户的最新推文"""
    print(f"📥 抓取 @{username} ...")

    try:
        # 获取用户信息
        user = await client.get_user_by_screen_name(username)
        if not user:
            print(f"  ⚠️  未找到用户 @{username}")
            return []

        # 获取推文
        tweets = await client.get_user_tweets(user.id, "Tweets", count=TWEETS_PER_ACCOUNT)

        result = []
        for tweet in tweets:
            result.append({
                "username": username,
                "text": tweet.text,
                "created_at": tweet.created_at,
                "likes": tweet.favorite_count or 0,
                "retweets": tweet.retweet_count or 0,
            })
            print(f"  ✓ {tweet.text[:60]}...")

        return result

    except Exception as e:
        print(f"  ❌ 抓取 @{username} 失败: {e}")
        return []


async def fetch_all_tweets() -> list[dict]:
    """抓取所有账号的推文"""
    client = Client("en-US")
    await login(client)

    all_tweets = []
    for username in ACCOUNTS:
        tweets = await fetch_user_tweets(client, username)
        all_tweets.extend(tweets)
        # 避免请求过快被限流
        await asyncio.sleep(2)

    return all_tweets


def main():
    """主函数"""
    tweets = asyncio.run(fetch_all_tweets())
    return tweets


if __name__ == "__main__":
    tweets = main()
    print(f"\n📊 共抓取 {len(tweets)} 条推文")
    for t in tweets:
        print(f"  @{t['username']}: {t['text'][:60]}...")
