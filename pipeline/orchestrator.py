"""
管道编排器：调度翻译、洞察、拼装步骤

- Step 2: 翻译
- Step 3: 洞察分析（等翻译完成后再跑）
- Step 5: 纯本地拼装
- 支持断点续跑：中间文件存在则跳过对应步骤
"""

import os
from pathlib import Path

from config import AI_BASE_URL, AI_FALLBACK_PROVIDERS, AI_MODEL, AI_MODEL_INSIGHTS, AI_MODEL_TRANSLATE
from pipeline import Color, load_json, save_json
from pipeline.assemble import assemble
from pipeline.curate import curate
from pipeline.insights import run_insights
from pipeline.translate import needs_translation, run_translate
from pipeline.usage import usage_tracker

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))

# 中间缓存最多保留的条目数（防止无限增长）
_MAX_CACHE_ENTRIES = 2000
INSIGHT_MIN_COVERAGE = float(os.getenv("INSIGHT_MIN_COVERAGE", "0.8"))
# 0.35 只拦截灾难性失败；正常批次通常在 40-80%
TRANSLATION_MIN_COVERAGE = float(os.getenv("TRANSLATION_MIN_COVERAGE", "0.35"))


def _prune_intermediate(intermediate_dir: Path, active_ids: set[str]):
    """清理中间缓存中不在本次推文列表里的旧条目，防止文件无限增长"""
    for filename in ("jev_scores.json", "translations.json", "insights.json"):
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
    print(f"  {Color.GREY}📡 打分: Jev | 翻译: {AI_MODEL_TRANSLATE} | 洞察: {AI_MODEL_INSIGHTS}  (兜底: {provider_host}/{AI_MODEL} + {fallback_count} 个降级){Color.RESET}")

    # Phase 0: 规则化预过滤（零 LLM 调用）
    tweets = curate(tweets)

    if not tweets:
        print(f"\n{Color.RED}⚠️ 预过滤后无剩余推文{Color.RESET}")
        return "", ""

    # Phase 0.5: Jev 类型化打分与精选
    print(f"\n{Color.BOLD}━━━ Phase 0.5: Jev 打分 ━━━{Color.RESET}")
    from pipeline.score import run_score
    tweets = await run_score(tweets, intermediate_dir, force_rerun)

    if not tweets:
        print(f"\n{Color.RED}⚠️ Jev 打分后无剩余推文{Color.RESET}")
        return "", ""

    # 更新 active_ids（预过滤和打分可能大幅删减了推文）
    active_ids = {str(t["tweet_id"]) for t in tweets}

    # Phase 1: 翻译
    print(f"\n{Color.BOLD}━━━ Phase 1: 翻译 ━━━{Color.RESET}")
    translations = await run_translate(tweets, intermediate_dir, force_rerun)

    need_translation = [t for t in tweets if needs_translation(t.get("text", ""))]
    translated = [
        t
        for t in need_translation
        if str(translations.get(str(t["tweet_id"]), "SKIP")).strip().upper() != "SKIP"
    ]
    translation_coverage = (
        len(translated) / len(need_translation) if need_translation else 1.0
    )
    print(
        f"  {Color.GREY}🌐 翻译覆盖率: {len(translated)}/{len(need_translation)} "
        f"= {translation_coverage:.0%}{Color.RESET}"
    )
    if need_translation and translation_coverage < TRANSLATION_MIN_COVERAGE:
        raise RuntimeError(
            f"翻译覆盖率过低（{len(translated)}/{len(need_translation)}），"
            "已中止，避免推送半份报告"
        )

    # Phase 2: 洞察分析（需要翻译上下文）
    print(f"\n{Color.BOLD}━━━ Phase 2: 洞察分析 ━━━{Color.RESET}")
    insights = await run_insights(tweets, translations, intermediate_dir, force_rerun)

    insight_coverage = len(insights) / len(tweets) if tweets else 1.0
    print(
        f"  {Color.GREY}🧠 洞察覆盖率: {len(insights)}/{len(tweets)} "
        f"= {insight_coverage:.0%}{Color.RESET}"
    )
    if insight_coverage < INSIGHT_MIN_COVERAGE:
        raise RuntimeError(
            f"洞察覆盖率过低（{len(insights)}/{len(tweets)}），"
            "已中止，避免推送半份报告"
        )

    # Phase 3: 纯本地拼装（原推链接直接用 x.com 原始 URL，无需缩链）
    print(f"\n{Color.BOLD}━━━ Phase 3: 本地装配 ━━━{Color.RESET}")
    markdown, counts = assemble(tweets, translations, insights)

    # Phase 4: 输出 LLM 用量汇总（按端点+模型聚合）
    usage_tracker.print_summary(header="LLM 调用与 Token 用量汇总")

    print(f"\n{Color.GREEN}✅ 管道完成{Color.RESET}")
    return markdown, counts
