"""
Step 0.5: Jev 类型化打分

用 TypeSafe Jev 对每条推文做三个独立判断：
  - signal  (Noul): 是否包含值得收录的实质信息
  - depth   (Score): 信息深度/重要性（5 个有序等级）
  - novelty (Noul): 是否提供新信息，而不是重复已知消息

代码把三个概率合成 0-100 的 quality，过滤后按质量取 Top N。
判断结果缓存到 output/intermediate/jev_scores.json，便于审计和调权重。

Jev 只做判断，不生成文本；翻译和洞察仍由后面的 LLM 步骤完成。
"""

import asyncio
import os
from pathlib import Path

from typesafe_sdk import AsyncTypeSafeClient, Noul, NoulCriteria, Score

from pipeline import Color, load_json, save_json

JEV_CONCURRENCY = int(os.getenv("JEV_CONCURRENCY", "10"))
JEV_MIN_SIGNAL = float(os.getenv("JEV_MIN_SIGNAL", "0.5"))
JEV_QUALITY_THRESHOLD = int(os.getenv("JEV_QUALITY_THRESHOLD", "80"))
JEV_MAX_RETRIES = 3

QUALITY_WEIGHTS = {
    "depth": 0.5,
    "signal": 0.3,
    "novelty": 0.2,
}

SIGNAL_QUESTION = Noul(
    instructions=(
        "Does this tweet contain substantive information worth including in a "
        "technology intelligence digest? Substantive information means facts, "
        "data, research results, product launches, verifiable opinions, or deep "
        "analysis. Exclude pure emotion, small talk, ads, giveaways, link-only "
        "posts, and retweets with no added information."
    ),
    criteria=NoulCriteria(
        true="The tweet itself states concrete facts, data, an opinion, or a development that gives the reader new information.",
        false="The tweet is only emotion, small talk, an ad, a slogan, a link, or an information-free retweet.",
    ),
)

NOVELTY_QUESTION = Noul(
    instructions=(
        "Does this tweet add new information or a new angle rather than merely "
        "repeating a story that is already known?"
    ),
    criteria=NoulCriteria(
        true="It contains a new development, data point, opinion, or detail not already covered.",
        false="It only repeats a known item, is a routine retweet, or adds no new information.",
    ),
)

DEPTH_QUESTION = Score(
    instructions=(
        "How deep and important is the information in this tweet? "
        "Use the five ordered levels below."
    ),
    criteria=[
        "Pure noise or chatter with no information value",
        "Routine update or generic commentary with little reference value",
        "Some information value, such as a normal update or ordinary opinion",
        "Important industry information, data, or deep analysis",
        "Major breakthrough, exclusive data, or major event",
    ],
)

QUESTIONS = {
    "signal": SIGNAL_QUESTION,
    "depth": DEPTH_QUESTION,
    "novelty": NOVELTY_QUESTION,
}


def _state_for(tweet: dict) -> dict:
    return {
        "tweet": {
            "author": tweet.get("username", ""),
            "text": tweet.get("text", ""),
            "created_at": tweet.get("created_at", ""),
            "is_retweet": bool(tweet.get("is_retweet")),
        },
        "audience": "Chinese-language technology intelligence digest readers",
    }


def _compose_quality(signal: float, depth: float, novelty: float) -> int:
    quality = 100 * (
        QUALITY_WEIGHTS["depth"] * depth
        + QUALITY_WEIGHTS["signal"] * signal
        + QUALITY_WEIGHTS["novelty"] * novelty
    )
    # 硬门槛：signal 低的推文无论深度如何都不进入日报
    if signal < JEV_MIN_SIGNAL:
        quality = min(quality, JEV_QUALITY_THRESHOLD - 1)
    return max(0, min(100, int(round(quality))))


async def _judge_tweet(client, semaphore, tweet: dict) -> tuple[str, dict]:
    tid = str(tweet["tweet_id"])
    async with semaphore:
        last_error = None
        for attempt in range(1, JEV_MAX_RETRIES + 1):
            try:
                response = await client.system_one(
                    state=_state_for(tweet),
                    questions=QUESTIONS,
                )
                signal = float(response.nouls["signal"].noul)
                depth = float(response.scores["depth"].score)
                novelty = float(response.nouls["novelty"].noul)
                confidence = response.scores["depth"].confidence
                return tid, {
                    "quality": _compose_quality(signal, depth, novelty),
                    "signal": round(signal, 4),
                    "depth": round(depth, 4),
                    "novelty": round(novelty, 4),
                    "depth_confidence": round(float(confidence), 4)
                    if confidence is not None
                    else None,
                }
            except Exception as e:
                last_error = e
                if attempt < JEV_MAX_RETRIES:
                    await asyncio.sleep(2 ** (attempt - 1))
        return tid, {"error": f"{type(last_error).__name__}: {last_error}"}


async def _judge_all(tweets: list[dict]) -> list[tuple[str, dict]]:
    if not os.getenv("TYPESAFE_API_KEY"):
        raise RuntimeError("未配置 TYPESAFE_API_KEY，Jev 打分无法运行")

    model = os.getenv("TYPESAFE_DEFAULT_MODEL") or "jev-latest"
    semaphore = asyncio.Semaphore(JEV_CONCURRENCY)
    async with AsyncTypeSafeClient(model=model) as client:
        return await asyncio.gather(
            *[_judge_tweet(client, semaphore, t) for t in tweets]
        )


async def run_score(
    tweets: list[dict],
    intermediate_dir: Path,
    force_rerun: bool = False,
) -> list[dict]:
    """用 Jev 打分、过滤并排序，返回进入后续管线的推文。"""
    cache_file = intermediate_dir / "jev_scores.json"
    raw_cache = {} if force_rerun else load_json(cache_file)

    active_ids = {str(t["tweet_id"]) for t in tweets}
    cache = {
        k: v
        for k, v in raw_cache.items()
        if k in active_ids and isinstance(v, dict) and "quality" in v
    }
    to_process = [t for t in tweets if str(t["tweet_id"]) not in cache]

    if not to_process:
        print(f"  {Color.GREEN}✓ Jev 打分缓存完全命中{Color.RESET}")
    else:
        print(
            f"  {Color.CYAN}🧠 Jev 打分 {len(to_process)} 条推文"
            f"（并发 {JEV_CONCURRENCY}，模型 {os.getenv('TYPESAFE_DEFAULT_MODEL') or 'jev-latest'}）...{Color.RESET}"
        )
        results = await _judge_all(to_process)

        errors = []
        for tid, verdict in results:
            if "error" in verdict:
                errors.append((tid, verdict["error"]))
            else:
                cache[tid] = verdict
        save_json(cache_file, cache)

        if errors:
            print(
                f"  {Color.YELLOW}⚠️ Jev 失败 {len(errors)}/{len(to_process)} 条，"
                f"示例: {errors[:2]}{Color.RESET}"
            )
            if len(errors) > max(10, int(len(to_process) * 0.2)):
                raise RuntimeError(
                    f"Jev 打分失败率过高（{len(errors)}/{len(to_process)}），已中止"
                )

    scored = []
    for t in tweets:
        tid = str(t["tweet_id"])
        quality = int(cache.get(tid, {}).get("quality", 0))
        t["quality"] = quality
        if quality >= JEV_QUALITY_THRESHOLD:
            scored.append(t)

    scored.sort(key=lambda t: (t["quality"], str(t["tweet_id"])), reverse=True)
    high_quality_count = len(scored)

    # Jev 的 80 分线可能偏严；至少保证 60 条进入后续管线，避免空报告
    if high_quality_count < 60 and tweets:
        existing = {str(t["tweet_id"]) for t in scored}
        rest = [t for t in tweets if str(t["tweet_id"]) not in existing]
        rest.sort(key=lambda t: (t["quality"], str(t["tweet_id"])), reverse=True)
        scored.extend(rest[: 60 - high_quality_count])
        scored.sort(key=lambda t: (t["quality"], str(t["tweet_id"])), reverse=True)
        print(
            f"  {Color.YELLOW}⚠️ >= {JEV_QUALITY_THRESHOLD} 分只有 {high_quality_count} 条，"
            f"已按 Jev 排序补足到 {len(scored)} 条{Color.RESET}"
        )

    keep_ratio = 0.3
    keep_count = max(60, min(180, int(len(scored) * keep_ratio)))
    top_n = scored[:keep_count]

    print(
        f"  {Color.GREEN}📊 Jev 打分完成，从 {len(tweets)} 条中精选出 {len(top_n)} 条"
        f"（>= {JEV_QUALITY_THRESHOLD} 分 {high_quality_count} 条，"
        f"取前 {keep_ratio:.0%} = {keep_count} 条）{Color.RESET}"
    )
    return top_n
