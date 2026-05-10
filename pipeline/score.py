"""
Step 0.5: 纯异步多模型并行打分

在翻译之前运行，用三个不同规格的 DeepSeek 模型对原文同时打分，取平均分。
从而提前过滤掉垃圾信息，大幅节省后续翻译和洞察步骤的时间与 Token 成本。
"""
import asyncio
import json
import os
from pathlib import Path

from openai import OpenAI

from pipeline import Color, extract_json, load_json, save_json
from config import AI_BATCH_SIZE

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
    使用三模型联合打分，过滤出平均分 >= 80 的推文，并取 Top 60。
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
        print(f"  {Color.CYAN}⚖️ 开始使用三模型引擎并行打分 {len(to_process)} 条推文...{Color.RESET}")
        
        sensenova_key = os.getenv("SENSENOVA_API_KEY")
        siliconflow_key = os.getenv("SILICONFLOW_API_KEY")
        
        sn_client = OpenAI(api_key=sensenova_key, base_url="https://api.sensenova.cn/compatible-mode/v2") if sensenova_key else None
        sf_client = OpenAI(api_key=siliconflow_key, base_url="https://api.siliconflow.cn/v1") if siliconflow_key else None
        
        models = []
        if sn_client: 
            models.append((sn_client, "DeepSeek-V3-1"))
            models.append((sn_client, "DeepSeek-R1"))
            
        if not models:
            print(f"  {Color.YELLOW}⚠️ 未配置商汤 API Key，无法执行联合打分，回退全部给100分{Color.RESET}")
            for t in to_process:
                scores_cache[str(t["tweet_id"])] = 100
        else:
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
