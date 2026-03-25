"""
Step 3: 专注洞察与分类

在翻译完成后运行，LLM 拿到原文 + 翻译上下文，专注于深度分析和分类。
"""

import asyncio
import json
from datetime import date
from pathlib import Path

from config import AI_BATCH_SIZE, AI_BATCH_COOLDOWN, AI_MODEL_INSIGHTS
from pipeline import call_ai_with_retry, extract_json, load_json, save_json, Color

INSIGHTS_PROMPT_TEMPLATE = """\
你是资深科技情报分析师。对每条推文进行质量评估、深度分析和分类。
当前日期：{current_date}

输出要求：
- quality: 1-5 信息价值评分
  5 = 重大事件/独家数据/突破性技术（如融资、产品发布、政策变动）
  4 = 有实质内容的行业观点或趋势分析
  3 = 有一定参考价值的信息或评论
  2 = 碎片化信息、转发无附加观点、泛泛而谈
  1 = 无信息量（纯表情、纯链接、广告、闲聊）

- thought: 针对 quality >= 3 的推文，写 2-3 句精炼分析。
  根据内容性质选择分析角度（技术趋势/商业影响/政策含义/行业格局），
  不要对每条都强行套投资逻辑。
  quality < 3 的推文，thought 输出 "SKIP"。

- category: 从以下选最匹配的：
  核心头条（仅限：重大产品发布、大额融资、政策变动、突发事件等具有广泛影响力的头条新闻）
  AI & 算法、芯片 & 硬件、航天 & 自动驾驶、
  市场 & 投资、政治 & 政策、F1 赛车、当代艺术

输出严格的 JSON 数组: [{{"id": "推文ID", "quality": 数字, "thought": "...", "category": "..."}}]
不要输出任何 JSON 之外的内容"""


async def run_insights(
    tweets: list[dict],
    translations: dict,
    intermediate_dir: Path,
    force_rerun: bool = False,
) -> dict:
    """
    生成洞察与分类。

    返回 {tweet_id: {"thought": str, "category": str, "quality": int}}
    """
    # ── 1. 加载并过滤缓存（会话隔离） ──
    cache_file = intermediate_dir / "insights.json"
    raw_cache: dict = {} if force_rerun else load_json(cache_file)
    
    active_ids = {str(t["tweet_id"]) for t in tweets}
    # 仅保留本次需要的缓存，防止 30 天前的历史数据干扰条数统计
    insights = {k: v for k, v in raw_cache.items() if k in active_ids}

    to_process = [t for t in tweets if str(t["tweet_id"]) not in insights]

    if not to_process:
        print(f"  {Color.GREEN}✓ 洞察缓存命中，跳过分析步骤{Color.RESET}")
        return insights

    print(f"  {Color.CYAN}🧠 开始分析 {len(to_process)} 条推文...{Color.RESET}")

    # 注入当前日期到 prompt
    insights_prompt = INSIGHTS_PROMPT_TEMPLATE.format(current_date=date.today().isoformat())

    # ── 2. 分批处理（弹性上限，利用长上下文模型优势） ──
    safe_batch_size = min(AI_BATCH_SIZE, 30)
    chunks = [to_process[i : i + safe_batch_size] for i in range(0, len(to_process), safe_batch_size)]

    for idx, chunk in enumerate(chunks):
        # 构造输入：原文 + 翻译
        tweet_input = []
        for t in chunk:
            tid = str(t["tweet_id"])
            entry = {"id": tid, "text": t["text"]}
            trans = translations.get(tid, "SKIP")
            if trans and trans.upper() != "SKIP":
                entry["translation"] = trans
            tweet_input.append(entry)

        input_text = json.dumps(tweet_input, ensure_ascii=False)

        print(f"  🧠 分析批次 ({idx + 1}/{len(chunks)})...")
        try:
            response = await asyncio.to_thread(
                call_ai_with_retry,
                messages=[
                    {"role": "system", "content": insights_prompt},
                    {"role": "user", "content": input_text},
                ],
                temperature=0.3,
                model_override=AI_MODEL_INSIGHTS,
            )
            items = extract_json(response.choices[0].message.content)
            for item in items:
                tid = str(item.get("id", ""))
                if tid:
                    insights[tid] = {
                        "thought": item.get("thought", ""),
                        "category": item.get("category", "其他动态"),
                        "quality": int(item.get("quality", 3)),
                    }

            # 持久化全量缓存
            raw_cache.update(insights)
            save_json(cache_file, raw_cache)

            if idx < len(chunks) - 1:
                await asyncio.sleep(AI_BATCH_COOLDOWN)

        except Exception as e:
            print(f"  {Color.RED}⚠️ 分析批次 {idx + 1} 失败: {e}{Color.RESET}")

    print(f"  {Color.GREEN}✓ 分析完成：{len(insights)} 条{Color.RESET}")
    return insights
