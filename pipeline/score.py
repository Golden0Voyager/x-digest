"""
Step 0.5: 纯异步多模型并行打分

在翻译之前运行，用 **跨端点双引擎** 对原文同时打分，取平均分。
从而提前过滤掉垃圾信息，大幅节省后续翻译和洞察步骤的时间与 Token 成本。

双引擎组合（硬编码，2026-06 起）：
  - deepseek-v4-flash  → Token Plan (token.sensenova.cn)
    每 5h 150 次，32K 上下文，纯文本响应极快、强工具调用
    （从 sensenova-6.7-flash-lite 切换过来：6.7 的 256K 多模态给纯文本打分属大材小用，
      把它留给 insights 任务；v4-flash 更适合短输入快出结果的打分场景）
  - DeepSeek-R1-Distill-Qwen-14B → 主链 (api.sensenova.cn)
    永久免费，32K 上下文，单轮评分不受 reasoning_content 往返影响

跨端点的好处：两个请求走不同 baseurl，不会在主链 1 QPS / 6 RPM 限制上
互相排队；Token Plan 配额独立，不消耗主链每日 5000 万 token 额度。

参考：
  - docs/api/sensenova-best-practices.md
  - docs/api/sensenova-token-plan-usage.md
"""
import asyncio
import json
import os
from pathlib import Path

from openai import OpenAI

from config import (
    AI_BATCH_COOLDOWN,
    AI_BATCH_SIZE_TP,
    SENSENOVA_TP_API_KEY,
    SENSENOVA_TP_BASE_URL,
)
from pipeline import Color, extract_json, load_json, save_json
from pipeline.usage import usage_tracker


def _build_score_clients() -> list[tuple[OpenAI, str, str]]:
    """构造双引擎 client + model + base_url 列表。

    返回 [(client, model_name, base_url), ...]，任一 client 创建失败时跳过对应引擎。
    base_url 用于 usage_tracker 区分端点。
    """
    sensenova_key = os.getenv("SENSENOVA_API_KEY")
    clients: list[tuple[OpenAI, str, str]] = []

    # 引擎 1：Token Plan 上的 deepseek-v4-flash（打分专用，32K 上下文 + 强工具调用）
    if SENSENOVA_TP_API_KEY:
        tp_client = OpenAI(
            api_key=SENSENOVA_TP_API_KEY,
            base_url=SENSENOVA_TP_BASE_URL,
            timeout=180,
        )
        clients.append((tp_client, "deepseek-v4-flash", SENSENOVA_TP_BASE_URL))
    else:
        print(f"  {Color.YELLOW}⚠️ SENSENOVA_TP_API_KEY 未配置，跳过 Token Plan 引擎{Color.RESET}")

    # 引擎 2：主链 DeepSeek-R1-Distill-Qwen-14B
    sn_base = "https://api.sensenova.cn/compatible-mode/v2"
    if sensenova_key:
        sn_client = OpenAI(
            api_key=sensenova_key,
            base_url=sn_base,
            timeout=180,
        )
        clients.append((sn_client, "DeepSeek-R1-Distill-Qwen-14B", sn_base))
    else:
        print(f"  {Color.YELLOW}⚠️ SENSENOVA_API_KEY 未配置，跳过主链 Distill-14B 引擎{Color.RESET}")

    return clients

SCORE_PROMPT_TEMPLATE = """\
You are a senior tech intelligence analyst. Evaluate the information value of each tweet on a strict 0-100 scale.

Scoring Criteria:
95-100 = Groundbreaking headlines / exclusive data / major tech breakthroughs
85-94 = Substantial industry insights, deep trend analysis, or hard-core tech details
70-84 = Medium quality information or commentary with some reference value
40-69 = Fragmented information, basic updates, normal retweets, general talk
0-39 = Zero information value (pure emojis, links only, ads, meaningless chat)

Input will be a JSON array of tweets.
Output ONLY a JSON array with the exact structure (no markdown fences, just JSON):
[{"id": "tweet_id", "quality": score}]
"""

async def fetch_scores_from_model(
    client: OpenAI,
    model_name: str,
    base_url: str,
    chunk: list,
    prompt: str,
) -> tuple[dict, str | None]:
    input_data = [{"id": str(t["tweet_id"]), "text": t["text"]} for t in chunk]

    response = None
    for attempt in range(3):
        try:
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=model_name,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)}
                ],
                temperature=0.1,
                max_tokens=8192
            )
            break
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
                print(f"    {Color.YELLOW}⚠️ {model_name} 第 {attempt+1}/3 次失败 ({type(e).__name__})，{2**attempt}s 后重试...{Color.RESET}")
            else:
                usage_tracker.track_failure(model=model_name, base_url=base_url)
                print(f"  {Color.RED}⚠️ 模型 {model_name} 3 次重试均失败: {e}{Color.RESET}")
                return {}, "error"

    # 提取 finish_reason（length 表示输出被截断）
    finish_reason = None
    if response.choices:
        finish_reason = getattr(response.choices[0], "finish_reason", None)
    # 用量追踪：score 不走 call_ai_with_retry，需手动记一笔
    if response.usage:
        u = response.usage
        usage_tracker.track(
            model=model_name,
            base_url=base_url,
            prompt_tokens=u.prompt_tokens,
            completion_tokens=u.completion_tokens,
            finish_reason=finish_reason,
        )
    else:
        usage_tracker.track(
            model=model_name, base_url=base_url,
            prompt_tokens=0, completion_tokens=0, finish_reason=finish_reason,
        )
    content = response.choices[0].message.content
    items = extract_json(content)
    result = {str(item.get("id", "")): int(item.get("quality", 0)) for item in items if item.get("id")}

    # 单引擎覆盖率：返回条数 vs 输入条数
    missing = len(chunk) - len(result)
    if finish_reason == "length":
        print(f"    {Color.RED}⚠️ {model_name}: 输入 {len(chunk)} / 返回 {len(result)} / 缺失 {missing} (finish=length 截断！){Color.RESET}")
    elif missing > 0:
        print(f"    {Color.YELLOW}⚠️ {model_name}: 输入 {len(chunk)} / 返回 {len(result)} / 缺失 {missing}{Color.RESET}")
    else:
        print(f"    {Color.GREY}✓ {model_name}: 输入 {len(chunk)} / 返回 {len(result)}{Color.RESET}")

    return result, finish_reason

async def run_score(tweets: list[dict], intermediate_dir: Path, force_rerun: bool = False) -> list[dict]:
    """
    使用跨端点双引擎联合打分（deepseek-v4-flash + DeepSeek-R1-Distill-Qwen-14B），
    过滤出平均分 >= 80 的推文，并取 Top 60。
    将平均分注入到推文的 'quality' 字段中。

    批次大小使用 AI_BATCH_SIZE_TP（默认 60），同时受 TP 配额（150 次/5h）和
    主链上下文（32K）双重约束。
    """
    cache_file = intermediate_dir / "scores.json"
    raw_cache = {} if force_rerun else load_json(cache_file)

    active_ids = {str(t["tweet_id"]) for t in tweets}
    scores_cache = {k: v for k, v in raw_cache.items() if k in active_ids}

    to_process = [t for t in tweets if str(t["tweet_id"]) not in scores_cache]

    if not to_process:
        print(f"  {Color.GREEN}✓ 打分缓存完全命中{Color.RESET}")
    else:
        models = _build_score_clients()

        if not models:
            print(f"  {Color.YELLOW}⚠️ 未配置任何打分引擎 API Key，回退全部给 100 分{Color.RESET}")
            for t in to_process:
                scores_cache[str(t["tweet_id"])] = 100
        else:
            print(f"  {Color.CYAN}⚖️ 开始使用跨端点双引擎并行打分 {len(to_process)} 条推文 (批次 {AI_BATCH_SIZE_TP})...{Color.RESET}")
            print(f"  {Color.GREY}联合打分评委: {', '.join([m[1] for m in models])}{Color.RESET}")

            current_batch_size = AI_BATCH_SIZE_TP
            FALLBACK_BATCH_SIZE = 45

            idx = 0
            while idx < len(to_process):
                chunk = to_process[idx : idx + current_batch_size]
                print(f"  ⚖️ 打分批次 (剩余 {len(to_process) - idx} 条, 批 {len(chunk)} 条)...")
                tasks = [
                    fetch_scores_from_model(c, m, url, chunk, SCORE_PROMPT_TEMPLATE)
                    for c, m, url in models
                ]
                results = await asyncio.gather(*tasks)

                scores_results = [r[0] for r in results]
                finish_reasons = [r[1] for r in results]
                truncated = any(fr == "length" for fr in finish_reasons)

                # 计算平均分
                for t in chunk:
                    tid = str(t["tweet_id"])
                    valid_scores = [sr.get(tid) for sr in scores_results if tid in sr and sr.get(tid) is not None]
                    if valid_scores:
                        avg_score = int(sum(valid_scores) / len(valid_scores))
                    else:
                        avg_score = 0
                    scores_cache[tid] = avg_score

                if truncated and current_batch_size > FALLBACK_BATCH_SIZE:
                    old_size = current_batch_size
                    current_batch_size = FALLBACK_BATCH_SIZE
                    print(f"  {Color.YELLOW}⚠️ 检测到 length 截断，批次自动降级 {old_size} → {current_batch_size}{Color.RESET}")

                idx += len(chunk)
                # 批次间冷却：防止主链 6 RPM / Token Plan 配额触发限流
                if idx < len(to_process):
                    await asyncio.sleep(AI_BATCH_COOLDOWN)

            raw_cache.update(scores_cache)
            save_json(cache_file, raw_cache)

    # 过滤、注入打分并排序
    scored_tweets = []
    for t in tweets:
        tid = str(t["tweet_id"])
        score = scores_cache.get(tid, 0)
        # 注入质量分数
        t["quality"] = score
        if score >= 80:
            scored_tweets.append(t)

    # 按分数降序，再按 ID 降序排序
    scored_tweets.sort(key=lambda t: (t["quality"], str(t["tweet_id"])), reverse=True)

    # 动态比例：取高于 80 分推文的 30%，至少 30 条、至多 150 条
    keep_ratio = 0.3
    keep_count = max(60, min(180, int(len(scored_tweets) * keep_ratio)))
    top_n = scored_tweets[:keep_count]

    print(f"  {Color.GREEN}📊 打分完成，从 {len(tweets)} 条中精选出 {len(top_n)} 条（>=80分，取前 {keep_ratio:.0%} = {keep_count} 条）{Color.RESET}")
    return top_n
