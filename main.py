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
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_USER_ID = os.getenv("FEISHU_USER_ID", "")


# ===== 飞书 API =====

def get_feishu_token() -> str:
    """获取飞书 tenant_access_token"""
    resp = httpx.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") == 0:
        return data["tenant_access_token"]
    raise Exception(f"获取飞书 token 失败: {data}")


def send_feishu_message(text: str, msg_type: str = "text", content: dict | None = None):
    """通过龙虾助手给海宁发飞书消息"""
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_ID]):
        print("⚠️  飞书配置不完整，跳过推送")
        return

    try:
        token = get_feishu_token()
        if content is None:
            content = {"text": text}
        resp = httpx.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": "open_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": FEISHU_USER_ID,
                "msg_type": msg_type,
                "content": json.dumps(content),
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("code") == 0:
            print("📨 飞书消息发送成功！")
        else:
            print(f"⚠️  飞书发送失败: {data.get('msg', data)}")
    except Exception as e:
        print(f"⚠️  飞书发送异常: {e}")


def create_feishu_doc(title: str, markdown_content: str) -> str | None:
    """创建飞书文档并写入内容，返回文档 URL"""
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET]):
        print("⚠️  飞书配置不完整，跳过文档创建")
        return None

    try:
        token = get_feishu_token()
        headers = {"Authorization": f"Bearer {token}"}

        # 1. 创建文档
        resp = httpx.post(
            "https://open.feishu.cn/open-apis/docx/v1/documents",
            headers=headers,
            json={"title": title},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            print(f"⚠️  创建文档失败: {data.get('msg', data)}")
            return None

        doc_id = data["data"]["document"]["document_id"]
        doc_url = f"https://bqy26cs08l.feishu.cn/docx/{doc_id}"
        print(f"📄 文档已创建: {doc_url}")

        # 2. 获取文档根 block_id
        resp = httpx.get(
            f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}",
            headers=headers,
            timeout=10,
        )
        root_data = resp.json()
        if root_data.get("code") != 0:
            print(f"⚠️  获取文档信息失败: {root_data.get('msg', root_data)}")
            return doc_url

        # 3. 将 markdown 分段写入文档（每行一个 block）
        lines = markdown_content.strip().split("\n")
        children = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # 判断标题级别
            if stripped.startswith("### "):
                children.append({
                    "block_type": 5,  # heading3
                    "heading3": {
                        "elements": [{"text_run": {"content": stripped[4:]}}],
                        "style": {},
                    },
                })
            elif stripped.startswith("## "):
                children.append({
                    "block_type": 4,  # heading2
                    "heading2": {
                        "elements": [{"text_run": {"content": stripped[3:]}}],
                        "style": {},
                    },
                })
            elif stripped.startswith("# "):
                children.append({
                    "block_type": 3,  # heading1
                    "heading1": {
                        "elements": [{"text_run": {"content": stripped[2:]}}],
                        "style": {},
                    },
                })
            elif stripped.startswith("---"):
                children.append({
                    "block_type": 22,  # divider
                    "divider": {},
                })
            elif stripped.startswith("- "):
                children.append({
                    "block_type": 2,  # text (bullet style)
                    "text": {
                        "elements": [{"text_run": {"content": f"• {stripped[2:]}"}}],
                        "style": {},
                    },
                })
            else:
                # 处理加粗文本
                elements = []
                parts = stripped.split("**")
                for i, part in enumerate(parts):
                    if not part:
                        continue
                    if i % 2 == 1:  # 奇数位是加粗内容
                        elements.append({
                            "text_run": {
                                "content": part,
                                "text_element_style": {"bold": True},
                            }
                        })
                    else:
                        elements.append({"text_run": {"content": part}})
                if not elements:
                    continue
                children.append({
                    "block_type": 2,  # text
                    "text": {"elements": elements, "style": {}},
                })

        # 分批写入（每批最多 50 个 block）
        batch_size = 50
        for i in range(0, len(children), batch_size):
            batch = children[i : i + batch_size]
            resp = httpx.post(
                f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                headers=headers,
                json={"children": batch},
                timeout=30,
            )
            batch_data = resp.json()
            if batch_data.get("code") != 0:
                print(f"⚠️  写入文档内容失败 (batch {i}): {batch_data.get('msg', batch_data)}")

        print(f"✅ 文档内容写入完成")
        return doc_url

    except Exception as e:
        print(f"⚠️  飞书文档创建异常: {e}")
        return None


# ===== AI 处理 =====

def translate_and_summarize(tweets: list[dict]) -> str:
    """使用 AI 翻译并总结推文"""
    if not tweets:
        return ""

    input_text = "\n\n".join(
        [f"@{t['username']} ({t['created_at']}):\n{t['text']}" for t in tweets]
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


def generate_highlights(summary: str) -> str:
    """从总结中提取亮点摘要"""
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


# ===== 输出 =====

def save_output(content: str, tweet_count: int) -> Path:
    """保存输出到 Markdown 文件"""
    date = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M")
    output_path = OUTPUT_DIR / f"{date}-{time_str}.md"

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


# ===== 主函数 =====

def main():
    print("🚀 X-Digest 启动\n")

    # 1. 抓取推文
    all_tweets = asyncio.run(fetch_all_tweets())
    print(f"\n📊 共抓取 {len(all_tweets)} 条推文\n")

    if not all_tweets:
        print("⚠️  没有新推文，跳过总结")
        send_feishu_message("📰 X-Digest：最近无新推文，本轮跳过。")
        return

    # 2. AI 翻译总结
    summary = translate_and_summarize(all_tweets)

    # 3. 生成亮点摘要
    highlights = generate_highlights(summary)

    # 4. 保存本地文件
    save_output(summary, len(all_tweets))

    # 5. 创建飞书文档
    date = datetime.now().strftime("%Y-%m-%d")
    doc_title = f"X 科技摘要 · {date}"
    full_md = f"""生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
数据来源：{len(all_tweets)} 条推文
监控账号：100 个

---

{summary}"""
    doc_url = create_feishu_doc(doc_title, full_md)

    # 6. 发飞书消息（带文档链接）
    date_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    if doc_url:
        msg = f"""📰 X 科技摘要 · {date_time}

📊 {len(all_tweets)} 条推文 | 100 个账号

🔥 今日亮点：
{highlights}

📄 完整报告：{doc_url}"""
    else:
        msg = f"""📰 X 科技摘要 · {date_time}

📊 {len(all_tweets)} 条推文 | 100 个账号

🔥 今日亮点：
{highlights}

💡 完整报告已保存到本地 output/ 目录"""

    send_feishu_message(msg)

    print("\n✅ 完成！")


if __name__ == "__main__":
    main()
