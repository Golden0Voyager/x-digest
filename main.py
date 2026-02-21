"""
X (Twitter) 摘要生成器 - 主程序

抓取推文 → 翻译 → 总结 → 输出 → 飞书推送
"""

import os
import asyncio
import json
from datetime import datetime
from pathlib import Path

import httpx
from openai import OpenAI
from dotenv import load_dotenv

from config import SUMMARY_PROMPT
from fetcher import fetch_all_tweets

# 加载环境变量
load_dotenv()

# 阿里云百炼 API (兼容 OpenAI 格式)
dashscope_client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# 输出目录
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
OUTPUT_DIR.mkdir(exist_ok=True)

# 飞书配置
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")


def translate_and_summarize(tweets: list[dict]) -> str:
    """使用 AI 翻译并总结推文"""
    if not tweets:
        return ""

    input_text = "\n\n".join(
        [
            f"@{t['username']} ({t['created_at']}):\n{t['text']}"
            for t in tweets
        ]
    )

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


def generate_highlights(summary: str, tweet_count: int) -> str:
    """从总结中提取亮点摘要（用于飞书消息）"""
    print("🤖 生成亮点摘要...")

    response = dashscope_client.chat.completions.create(
        model=os.getenv("DASHSCOPE_MODEL", "deepseek-r1-distill-llama-70b"),
        messages=[
            {
                "role": "system",
                "content": "你是一位科技资讯编辑。请从以下日报中提取 5 条最重要的亮点，每条一句话，用 emoji 开头。只输出亮点列表，不要其他内容。",
            },
            {"role": "user", "content": summary},
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
监控账号：100 个

---

{content}
"""

    output_path.write_text(full_content, encoding="utf-8")
    print(f"💾 已保存：{output_path}")

    return output_path


def send_to_feishu(summary: str, highlights: str, tweet_count: int, doc_url: str = ""):
    """发送到飞书群机器人"""
    if not FEISHU_WEBHOOK_URL:
        print("⚠️  未配置 FEISHU_WEBHOOK_URL，跳过飞书推送")
        return

    date = datetime.now().strftime("%Y-%m-%d")

    # 构建飞书消息（富文本格式）
    content = f"""📰 X 科技摘要 · {date}

📊 数据：{tweet_count} 条推文 | 100 个账号

🔥 今日亮点：
{highlights}"""

    if doc_url:
        content += f"\n\n📄 完整报告：{doc_url}"

    payload = {
        "msg_type": "text",
        "content": {"text": content},
    }

    try:
        resp = httpx.post(FEISHU_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            if result.get("code") == 0 or result.get("StatusCode") == 0:
                print("📨 飞书消息发送成功！")
            else:
                print(f"⚠️  飞书返回错误：{result}")
        else:
            print(f"⚠️  飞书请求失败：{resp.status_code}")
    except Exception as e:
        print(f"⚠️  飞书发送异常：{e}")


def main():
    """主函数"""
    print("🚀 X-Digest 启动\n")

    # 1. 抓取推文
    all_tweets = asyncio.run(fetch_all_tweets())

    print(f"\n📊 共抓取 {len(all_tweets)} 条推文\n")

    if not all_tweets:
        print("⚠️  没有新推文，跳过总结")
        return

    # 2. AI 翻译总结
    summary = translate_and_summarize(all_tweets)

    # 3. 生成亮点摘要
    highlights = generate_highlights(summary, len(all_tweets))

    # 4. 保存本地文件
    save_output(summary, len(all_tweets))

    # 5. 发送飞书通知
    send_to_feishu(summary, highlights, len(all_tweets))

    print("\n✅ 完成！")


if __name__ == "__main__":
    main()
