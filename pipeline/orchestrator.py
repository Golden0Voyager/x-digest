"""
管道编排器：调度翻译、洞察、拼装步骤

- Step 2: 翻译
- Step 3: 洞察分析（等翻译完成后再跑）
- Step 5: 纯本地拼装
- 支持断点续跑：中间文件存在则跳过对应步骤
"""

import asyncio
import os
from pathlib import Path

from pipeline import Color, load_json, save_json
from pipeline.curate import curate
from pipeline.translate import run_translate
from pipeline.insights import run_insights
from pipeline.assemble import assemble
from config import AI_MODEL, AI_BASE_URL, AI_FALLBACK_PROVIDERS, AI_MODEL_TRANSLATE, AI_MODEL_INSIGHTS

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))

# 中间缓存最多保留的条目数（防止无限增长）
_MAX_CACHE_ENTRIES = 2000


def _prune_intermediate(intermediate_dir: Path, active_ids: set[str]):
    """清理中间缓存中不在本次推文列表里的旧条目，防止文件无限增长"""
    for filename in ("translations.json", "insights.json"):
        path = intermediate_dir / filename
        data = load_json(path)
        if len(data) <= _MAX_CACHE_ENTRIES:
            continue
        pruned = {k: v for k, v in data.items() if k in active_ids}
        save_json(path, pruned)


async def run_pipeline(
    tweets: list[dict],
    force_rerun: bool = False,
) -> tuple[str, str]:
    """
    编排整个管道。

    返回 (markdown_content, counts_summary)
    """
    if not tweets:
        return "", ""

    intermediate_dir = OUTPUT_DIR / "intermediate"
    intermediate_dir.mkdir(parents=True, exist_ok=True)

    # 清理过大的中间缓存
    active_ids = {str(t["tweet_id"]) for t in tweets}
    _prune_intermediate(intermediate_dir, active_ids)

    print(f"\n{Color.CYAN}🚀 管道启动：{len(tweets)} 条推文待处理{Color.RESET}")
    # 从 base_url 提取供应商域名作为简称
    provider_host = AI_BASE_URL.split("//")[-1].split("/")[0].split(".")[1] if AI_BASE_URL else "unknown"
    fallback_count = len(AI_FALLBACK_PROVIDERS)
    print(f"  {Color.GREY}📡 打分: 跨端点双引擎 | 翻译: {AI_MODEL_TRANSLATE} | 洞察: {AI_MODEL_INSIGHTS}  (兜底: {provider_host}/{AI_MODEL} + {fallback_count} 个降级){Color.RESET}")

    # Phase 0: 规则化预过滤（零 LLM 调用）
    tweets = curate(tweets)

    if not tweets:
        print(f"\n{Color.RED}⚠️ 预过滤后无剩余推文{Color.RESET}")
        return "", ""

    # Phase 0.5: 联合打分与精选（V3-1 + R1 双模型并行）
    print(f"\n{Color.BOLD}━━━ Phase 0.5: 多模型联合打分 ━━━{Color.RESET}")
    from pipeline.score import run_score
    tweets = await run_score(tweets, intermediate_dir, force_rerun)

    if not tweets:
        print(f"\n{Color.RED}⚠️ 联合打分后无剩余推文（全低于 80 分）{Color.RESET}")
        return "", ""

    # 更新 active_ids（预过滤和打分可能大幅删减了推文）
    active_ids = {str(t["tweet_id"]) for t in tweets}

    # Phase 1: 翻译
    print(f"\n{Color.BOLD}━━━ Phase 1: 翻译 ━━━{Color.RESET}")
    translations = await run_translate(tweets, intermediate_dir, force_rerun)

    # Phase 2: 洞察分析（需要翻译上下文）
    print(f"\n{Color.BOLD}━━━ Phase 2: 洞察分析 ━━━{Color.RESET}")
    insights = await run_insights(tweets, translations, intermediate_dir, force_rerun)

    # Phase 3: 纯本地拼装（原推链接直接用 x.com 原始 URL，无需缩链）
    print(f"\n{Color.BOLD}━━━ Phase 3: 本地装配 ━━━{Color.RESET}")
    markdown, counts = assemble(tweets, translations, insights)

    print(f"\n{Color.GREEN}✅ 管道完成{Color.RESET}")
    return markdown, counts
