"""
测试模式 - 使用模拟数据测试 AI 翻译总结功能
"""

import json
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import os

# 加载环境变量
load_dotenv()

# 阿里云百炼 API (兼容 OpenAI 格式)
from openai import OpenAI

dashscope_client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 总结提示词
SUMMARY_PROMPT = """
你是一位科技资讯编辑。请将以下 Twitter 推文内容：
1. 翻译成中文
2. 按领域分类（AI、航天、机器人、经济、其他）
3. 提炼每条的核心要点（1-2 句话）
4. 如果有重要趋势或洞察，在开头写一段总结

保持简洁、专业、信息密度高。
"""


def load_test_tweets():
    """加载测试数据"""
    with open("test_tweets.json", "r", encoding="utf-8") as f:
        return json.load(f)


def translate_and_summarize(tweets: list[dict]) -> str:
    """使用 AI 翻译并总结推文"""
    # 准备输入文本
    input_text = "\n\n".join([
        f"@{t['username']} ({t['created_at'][:16]}):"
        f"\n{t['text']}"
        for t in tweets
    ])
    
    print("🤖 调用阿里云百炼 AI 翻译总结中...")
    
    response = dashscope_client.chat.completions.create(
        model=os.getenv("DASHSCOPE_MODEL", "qwen-plus"),
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": input_text},
        ],
        temperature=0.3,
    )
    
    return response.choices[0].message.content


def save_output(content: str):
    """保存输出"""
    date = datetime.now().strftime("%Y-%m-%d")
    output_path = Path(f"output/{date}-TEST.md")
    
    full_content = f"""# X 科技摘要 · {date} (测试版)

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
模型：{os.getenv('DEEPSEEK_MODEL', 'deepseek-r1-distill-llama-70b')}
测试数据：15 条模拟推文

---

{content}

---

## 说明

这是测试运行，使用模拟数据。等 Twitter API 激活后，将抓取真实推文。
"""
    
    output_path.write_text(full_content, encoding="utf-8")
    print(f"💾 已保存：{output_path}")
    return output_path


def main():
    print("🧪 X-Digest 测试模式\n")
    print("📊 加载测试数据...")
    
    tweets = load_test_tweets()
    print(f"✓ 已加载 {len(tweets)} 条模拟推文\n")
    
    # AI 翻译总结
    summary = translate_and_summarize(tweets)
    
    # 保存输出
    print("\n📝 生成报告中...")
    save_output(summary)
    
    print("\n✅ 测试完成！")
    print("\n📄 查看输出：output/YYYY-MM-DD-TEST.md")


if __name__ == "__main__":
    main()
