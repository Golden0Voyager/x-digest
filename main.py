"""
X (Twitter) 摘要生成器 - 主程序

抓取推文 → 翻译 → 总结 → 输出
"""

import os
from datetime import datetime
from pathlib import Path

import tweepy
from openai import OpenAI
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

from config import ACCOUNTS, TWEETS_PER_ACCOUNT, SUMMARY_PROMPT, LANGUAGE

# 加载环境变量
load_dotenv()

# 初始化客户端
twitter_client = tweepy.Client(bearer_token=os.getenv("TWITTER_BEARER_TOKEN"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 输出目录
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
OUTPUT_DIR.mkdir(exist_ok=True)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def fetch_tweets(username: str) -> list[dict]:
    """获取用户的最新推文"""
    print(f"📥 抓取 @{username} ...")
    
    # 获取用户 ID
    user = twitter_client.get_user(username=username)
    if not user.data:
        print(f"  ⚠️  未找到用户 @{username}")
        return []
    
    user_id = user.data.id
    
    # 获取推文
    tweets = twitter_client.get_users_tweets(
        id=user_id,
        max_results=TWEETS_PER_ACCOUNT,
        tweet_fields=["created_at", "text", "public_metrics"],
        exclude=["retweets", "replies"],  # 排除转发和回复
    )
    
    if not tweets.data:
        print(f"  ✓ 无新推文")
        return []
    
    result = []
    for tweet in tweets.data:
        result.append({
            "username": username,
            "text": tweet.text,
            "created_at": tweet.created_at,
            "likes": tweet.public_metrics.get("like_count", 0),
            "retweets": tweet.public_metrics.get("retweet_count", 0),
        })
        print(f"  ✓ {tweet.text[:50]}...")
    
    return result


def translate_and_summarize(tweets: list[dict]) -> str:
    """使用 AI 翻译并总结推文"""
    if not tweets:
        return ""
    
    # 准备输入文本
    input_text = "\n\n".join([
        f"@{t['username']} ({t['created_at'].strftime('%Y-%m-%d %H:%M')}):"
        f"\n{t['text']}"
        for t in tweets
    ])
    
    print("🤖 AI 翻译总结中...")
    
    response = openai_client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": input_text},
        ],
        temperature=0.3,
    )
    
    return response.choices[0].message.content


def save_output(content: str, date: str = None) -> Path:
    """保存输出到 Markdown 文件"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    output_path = OUTPUT_DIR / f"{date}.md"
    
    # 添加标题
    full_content = f"""# X 科技摘要 · {date}

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

{content}

---

## 原始推文统计

共抓取 {len([l for l in content.split('\\n') if l.strip()])} 条有效内容
"""
    
    output_path.write_text(full_content, encoding="utf-8")
    print(f"💾 已保存：{output_path}")
    
    return output_path


def main():
    """主函数"""
    print("🚀 X-Digest 启动\n")
    
    all_tweets = []
    
    # 抓取所有账号的推文
    for username in ACCOUNTS:
        tweets = fetch_tweets(username)
        all_tweets.extend(tweets)
    
    print(f"\n📊 共抓取 {len(all_tweets)} 条推文\n")
    
    if not all_tweets:
        print("⚠️  没有新推文，跳过总结")
        return
    
    # AI 翻译总结
    summary = translate_and_summarize(all_tweets)
    
    # 保存输出
    save_output(summary)
    
    print("\n✅ 完成！")


if __name__ == "__main__":
    main()
