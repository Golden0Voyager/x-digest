"""
Step 3: 专注洞察与分类 (科普增强版)

在联合打分和翻译完成后运行。
利用 sensenova-6.7-flash-lite（SenseNova Token Plan）的多模态 + 长上下文能力，
为非专业人士补全背景常识。

参考：
  - docs/api/sensenova-token-plan-usage.md
  - 端点：https://token.sensenova.cn/v1（与原 api.sensenova.cn 不同的服务）
  - 限速：每 5h 1500 次（远比原 1 QPS 宽松）
  - 降级：首选失败时自动回退到主链（V3-1 / R1）
"""

import asyncio
import json
from datetime import date
from pathlib import Path

from config import (
    AI_BATCH_SIZE, AI_BATCH_COOLDOWN, AI_MODEL_INSIGHTS, AI_MAX_BATCH_SIZE,
    SENSENOVA_TP_API_KEY, SENSENOVA_TP_BASE_URL,
)
from pipeline import call_ai_with_retry, extract_json, load_json, save_json, Color

INSIGHTS_PROMPT_TEMPLATE = """\
你是资深科技情报分析师。对这些精选推文进行深度分析、科普和分类。
当前日期：{current_date}

你的目标是：让非专业人士也能读懂硬核的科技/金融推文。

输出要求：
- background: 术语科普与背景补充。
  识别推文中的专业术语、缩写、技术架构或特定人物/事件背景（例如：MoE, H100, Fed Pivot, 某初创公司背景等）。
  用一句话、最通俗的语言进行“大白话”科普。
  如果没有需要科普的内容，请输入 "SKIP"。

- thought: 针对推文写 2-3 句精炼分析。
  结合当前的行业趋势，说明为什么这条推文重要。
  不要强行套用模板。如果实在没啥分析价值，请输入 "SKIP"。

- category: 从以下选最匹配的：
  核心头条、AI & 算法、芯片 & 硬件、航天 & 自动驾驶、市场 & 投资、政治 & 政策、F1 赛车、当代艺术

输出严格的 JSON 数组: [{{"id": "推文ID", "background": "...", "thought": "...", "category": "..."}}]
不要输出任何 JSON 之外的内容"""


async def run_insights(
    tweets: list[dict],
    translations: dict,
    intermediate_dir: Path,
    force_rerun: bool = False,
) -> dict:
    """
    生成洞察与分类。

    返回 {tweet_id: {"thought": str, "category": str, "quality": int, "background": str}}
    """
    cache_file = intermediate_dir / "insights.json"
    raw_cache: dict = {} if force_rerun else load_json(cache_file)
    
    active_ids = {str(t["tweet_id"]) for t in tweets}
    insights = {k: v for k, v in raw_cache.items() if k in active_ids}

    to_process = [t for t in tweets if str(t["tweet_id"]) not in insights]

    if not to_process:
        print(f"  {Color.GREEN}✓ 洞察缓存命中{Color.RESET}")
        for t in tweets:
            tid = str(t["tweet_id"])
            if tid in insights:
                insights[tid]["quality"] = t.get("quality", 80)
        return insights

    print(f"  {Color.CYAN}🧠 开始分析并科普 {len(to_process)} 条精选推文...{Color.RESET}")

    insights_prompt = INSIGHTS_PROMPT_TEMPLATE.format(current_date=date.today().isoformat())

    safe_batch_size = min(AI_BATCH_SIZE, AI_MAX_BATCH_SIZE)
    chunks = [to_process[i : i + safe_batch_size] for i in range(0, len(to_process), safe_batch_size)]

    for idx, chunk in enumerate(chunks):
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
                # 洞察任务走独立 Token Plan 端点（与主链 api.sensenova.cn 不同）
                # 失败时自动降级到主链的 V3-1 / R1
                base_url_override=SENSENOVA_TP_BASE_URL,
                api_key_override=SENSENOVA_TP_API_KEY,
                max_tokens=10000, # Token Plan 上下文 256K，输出上限更宽
            )
            items = extract_json(response.choices[0].message.content)
            for item in items:
                tid = str(item.get("id", ""))
                if tid:
                    original_tweet = next((t for t in chunk if str(t["tweet_id"]) == tid), {})
                    insights[tid] = {
                        "background": item.get("background", ""),
                        "thought": item.get("thought", ""),
                        "category": item.get("category", "其他动态"),
                        "quality": original_tweet.get("quality", 80),
                    }

            raw_cache.update(insights)
            save_json(cache_file, raw_cache)

            if idx < len(chunks) - 1:
                await asyncio.sleep(AI_BATCH_COOLDOWN)

        except Exception as e:
            print(f"  {Color.RED}⚠️ 分析批次 {idx + 1} 失败: {e}{Color.RESET}")

    print(f"  {Color.GREEN}✓ 分析与科普完成：{len(insights)} 条{Color.RESET}")
    return insights
