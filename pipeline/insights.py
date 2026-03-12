"""
Step 3: 专注洞察与分类

在翻译完成后运行，LLM 拿到原文 + 翻译上下文，专注于深度分析和分类。
"""

import asyncio
import json
from pathlib import Path

from config import AI_BATCH_SIZE, AI_BATCH_COOLDOWN, AI_MODEL_INSIGHTS
from pipeline import call_ai_with_retry, extract_json, load_json, save_json, Color

INSIGHTS_PROMPT = """\
你是资深科技情报分析师。为每条推文生成启发性思考和分类。
输入包含原文和翻译，你只需输出分析结果。

输出要求：
- thought: 3-4 句深度行业评论，分析背后的趋势、冲击或投资价值
- category: 从以下分类中选一个最匹配的：
  核心头条、AI & 算法、芯片 & 硬件、航天 & 自动驾驶、市场 & 投资、政治 & 政策、F1 赛车、当代艺术

输出严格的 JSON 数组: [{"id": "推文ID", "thought": "...", "category": "..."}]
不要输出任何 JSON 之外的内容"""


async def run_insights(
    tweets: list[dict],
    translations: dict,
    intermediate_dir: Path,
    force_rerun: bool = False,
) -> dict:
    """
    生成洞察与分类。

    返回 {tweet_id: {"thought": str, "category": str}}
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

    # ── 2. 分批处理（洞察分析耗费 Token 极多，强制更小的批次） ──
    safe_batch_size = min(AI_BATCH_SIZE, 12)
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
                    {"role": "system", "content": INSIGHTS_PROMPT},
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
