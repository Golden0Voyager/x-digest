import asyncio
from fetcher import fetch_all_tweets

async def main():
    print("🚀 开始测试抓取链路...")
    # 测试之前失败的账号
    test_accounts = ["drfeifei", "ylecun", "sama"]
    tweets = await fetch_all_tweets(accounts_list=test_accounts)
    print(f"\n✅ 抓取完成！共抓取 {len(tweets)} 条推文。")
    for i, t in enumerate(tweets[:5]):
        print(f"\n--- 推文 {i+1} ---")
        print(f"[{t['username']}] @ {t['created_at']}")
        print(t['text'][:100] + "...")

if __name__ == "__main__":
    asyncio.run(main())