"""
Step 0.5: 纯异步多模型并行打分

在翻译之前运行，用 **跨端点双引擎** 对原文同时打分，取平均分。
从而提前过滤掉垃圾信息，大幅节省后续翻译和洞察步骤的时间与 Token 成本。

双引擎组合（硬编码，2026-06 起）：
  - sensenova-6.7-flash-lite  → Token Plan (token.sensenova.cn)
    每 5h 1500 次，256K 上下文，与主链隔离的限速配额
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

from pipeline import Color, extract_json, load_json, save_json
from config import (
    AI_BATCH_SIZE, AI_BATCH_COOLDOWN,
    SENSENOVA_TP_API_KEY, SENSENOVA_TP_BASE_URL,
)


def _build_score_clients() -> list[tuple[OpenAI, str]]:
    """构造双引擎 client + model 列表。

    返回 [(client, model_name), ...]，任一 client 创建失败时跳过对应引擎。
    """
    sensenova_key = os.getenv("SENSENOVA_API_KEY")
    clients: list[tuple[OpenAI, str]] = []

    # 引擎 1：Token Plan 上的 sensenova-6.7-flash-lite
    if SENSENOVA_TP_API_KEY:
        tp_client = OpenAI(
            api_key=SENSENOVA_TP_API_KEY,
            base_url=SENSENOVA_TP_BASE_URL,
            timeout=180,
        )
        clients.append((tp_client, "sensenova-6.7-flash-lite"))
    else:
        print(f"  {Color.YELLOW}⚠️ SENSENOVA_TP_API_KEY 未配置，跳过 Token Plan 引擎{Color.RESET}")

    # 引擎 2：主链 DeepSeek-R1-Distill-Qwen-14B
    if sensenova_key:
        sn_client = OpenAI(
            api_key=sensenova_key,
            base_url="https://api.sensenova.cn/compatible-mode/v2",
            timeout=180,
        )
        clients.append((sn_client, "DeepSeek-R1-Distill-Qwen-14B"))
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

async def fetch_scores_from_model(client: OpenAI, model_name: str, chunk: list, prompt: str) -> dict:
    input_data = [{"id": str(t["tweet_id"]), "text": t["text"]} for t in chunk]
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model_name,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)}
            ],
            temperature=0.1,
            max_tokens=2048
        )
        content = response.choices[0].message.content
        items = extract_json(content)
        return {str(item.get("id", "")): int(item.get("quality", 0)) for item in items if item.get("id")}
    except Exception as e:
        print(f"  {Color.RED}⚠️ 模型 {model_name} 打分失败: {e}{Color.RESET}")
        return {}

async def run_score(tweets: list[dict], intermediate_dir: Path, force_rerun: bool = False) -> list[dict]:
    """
    使用跨端点双引擎联合打分（sensenova-6.7-flash-lite + DeepSeek-R1-Distill-Qwen-14B），
    过滤出平均分 >= 80 的推文，并取 Top 60。
    将平均分注入到推文的 'quality' 字段中。
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
            print(f"  {Color.CYAN}⚖️ 开始使用跨端点双引擎并行打分 {len(to_process)} 条推文...{Color.RESET}")
            print(f"  {Color.GREY}联合打分评委: {', '.join([m[1] for m in models])}{Color.RESET}")
            chunks = [to_process[i:i+AI_BATCH_SIZE] for i in range(0, len(to_process), AI_BATCH_SIZE)]

            for idx, chunk in enumerate(chunks):
                print(f"  ⚖️ 打分批次 ({idx+1}/{len(chunks)})...")
                tasks = [fetch_scores_from_model(c, m, chunk, SCORE_PROMPT_TEMPLATE) for c, m in models]
                results = await asyncio.gather(*tasks)

                # 计算平均分
                for t in chunk:
                    tid = str(t["tweet_id"])
                    valid_scores = [r.get(tid) for r in results if tid in r and r.get(tid) is not None]
                    if valid_scores:
                        avg_score = int(sum(valid_scores) / len(valid_scores))
                    else:
                        avg_score = 0
                    scores_cache[tid] = avg_score

                # 批次间冷却：防止主链 6 RPM / Token Plan 5h 1500 次触发限流
                if idx < len(chunks) - 1:
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

    # 截取 Top 60
    top_60 = scored_tweets[:60]

    print(f"  {Color.GREEN}📊 打分完成，从 {len(tweets)} 条中精选出 {len(top_60)} 条（>=80分且Top60）{Color.RESET}")
    return top_60
