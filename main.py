"""
X (Twitter) 摘要生成器 - 主程序

抓取推文 → 翻译 → 总结 → 输出
"""

import os
import asyncio
from datetime import datetime
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

from config import SUMMARY_PROMPT
from fetcher import fetch_all_tweets

# 加载环境变量
load_dotenv()

# 阿里云百炼 API (兼容 OpenAI 格式)
dashscope_client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 输出目录
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
OUTPUT_DIR.mkdir(exist_ok=True)


def translate_and_summarize(tweets: list[dict]) -> str:
    """使用 AI 翻译并总结推文"""
    if not tweets:
        return ""
    
    # 准备输入文本
    input_text = "\n\n".join([
        f"@{t['username']} ({t['created_at']}):"
        f"\n{t['text']}"
        f"\n❤️ {t['likes']}  🔁 {t['retweets']}"
        for t in tweets
    ])
    
    print("🤖 AI 翻译总结中...")
    
    response = dashscope_client.chat.completions.create(
        model=os.getenv("DASHSCOPE_MODEL", "deepseek-r1-distill-llama-70b"),
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": input_text},
        ],
        temperature=0.3,
    )
    
    return response.choices[0].message.content


def save_output(content: str, tweet_count: int, date: str = None) -> Path:
    """保存输出到 Markdown 文件"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    output_path = OUTPUT_DIR / f"{date}.md"
    
    full_content = f"""# X 科技摘要 · {date}

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
数据来源：{tweet_count} 条推文

---

{content}
"""
    
    output_path.write_text(full_content, encoding="utf-8")
    print(f"💾 已保存：{output_path}")
    
    return output_path


def main():
    """主函数"""
    print("🚀 X-Digest 启动\n")
    
    # 使用 Twikit 抓取推文
    all_tweets = asyncio.run(fetch_all_tweets())
    
    print(f"\n📊 共抓取 {len(all_tweets)} 条推文\n")
    
    if not all_tweets:
        print("⚠️  没有新推文，跳过总结")
        return
    
    # AI 翻译总结
    summary = translate_and_summarize(all_tweets)
    
    # 保存输出
    save_output(summary, len(all_tweets))
    
    print("\n✅ 完成！")


if __name__ == "__main__":
    main()
