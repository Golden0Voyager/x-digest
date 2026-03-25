"""
Step 2: 专注翻译

LLM 只做一件事 —— 将英文推文翻译为中文。
输出 JSON，逐批处理，缺失补译。
"""

import asyncio
import json
from pathlib import Path

from config import AI_BATCH_SIZE, AI_BATCH_COOLDOWN, AI_MODEL_TRANSLATE
from pipeline import call_ai_with_retry, extract_json, load_json, save_json, Color

TRANSLATE_PROMPT = """\
你是专业翻译官。将以下 X (Twitter) 推文翻译为中文。

### 核心规则：
1. **翻译判定**：只要原文包含英文单词或句子（哪怕只有 1-2 个词，如 "Wow", "Exactly"），就必须翻译。
2. **跳过判定**：只有当原文是【纯中文】、【纯表情符号】或【纯数字/符号】时，才输出 "SKIP"。
3. **处理 RT (转发)**：对于 "RT @username: content" 格式，请翻译后面的 content 部分。
4. **术语保留**：保留 AI/科技领域的专有名词（如 GPU, LLM, Transformer, Sora, RAG）。
5. **链接清理**：移除原文中的所有 t.co 链接，不要在译文中体现。
6. **格式一致**：严格输出 JSON 数组，确保输入中的每个 ID 都在输出中出现。

### 示例对照：
- 输入: {"id": "1", "text": "RT @ylecun: Proud to be part of the adventure!"}
  输出: {"id": "1", "translation": "转发自 @ylecun: 为能成为这段冒险的一部分而自豪！"}
- 输入: {"id": "2", "text": "Next-gen H100 is shipping soon."}
  输出: {"id": "2", "translation": "下一代 H100 即将出货。"}
- 输入: {"id": "3", "text": "今天天气不错 ☀️"}
  输出: {"id": "3", "translation": "SKIP"}
- 输入: {"id": "4", "text": "Exactly!"}
  输出: {"id": "4", "translation": "正是如此！"}

输出严格的 JSON 数组，不要包含任何 Markdown 代码块标签（如 ```json）或任何解释文字。"""


async def run_translate(
    tweets: list[dict],
    intermediate_dir: Path,
    force_rerun: bool = False,
) -> dict:
    """
    翻译推文。

    返回 {tweet_id: translation_text}，纯中文推文为 "SKIP"。
    """
    # ── 1. 加载并过滤缓存（会话隔离） ──
    cache_file = intermediate_dir / "translations.json"
    raw_cache: dict = {} if force_rerun else load_json(cache_file)
    
    active_ids = {str(t["tweet_id"]) for t in tweets}
    # 仅保留本次需要的缓存，防止 30 天前的历史数据干扰条数统计
    translations = {k: v for k, v in raw_cache.items() if k in active_ids}

    # 筛选真正需要调 AI 翻译的推文
    to_process = [t for t in tweets if str(t["tweet_id"]) not in translations]

    if not to_process:
        print(f"  {Color.GREEN}✓ 翻译缓存命中，跳过翻译步骤{Color.RESET}")
        return translations

    print(f"  {Color.CYAN}🌐 开始翻译 {len(to_process)} 条推文...{Color.RESET}")

    # ── 2. 分批处理（弹性上限，利用长上下文模型优势） ──
    safe_batch_size = min(AI_BATCH_SIZE, 30)
    chunks = [to_process[i : i + safe_batch_size] for i in range(0, len(to_process), safe_batch_size)]

    for idx, chunk in enumerate(chunks):
        tweet_input = [{"id": str(t["tweet_id"]), "text": t["text"]} for t in chunk]
        input_text = json.dumps(tweet_input, ensure_ascii=False)

        print(f"  🌐 翻译批次 ({idx + 1}/{len(chunks)})...")
        try:
            response = await asyncio.to_thread(
                call_ai_with_retry,
                messages=[
                    {"role": "system", "content": TRANSLATE_PROMPT},
                    {"role": "user", "content": input_text},
                ],
                temperature=0.2,
                model_override=AI_MODEL_TRANSLATE,
            )
            items = extract_json(response.choices[0].message.content)
            for item in items:
                tid = str(item.get("id", ""))
                if tid:
                    translations[tid] = item.get("translation", "SKIP")

            # 每批次持久化全量缓存（包含历史但返回时过滤）
            raw_cache.update(translations)
            save_json(cache_file, raw_cache)

            if idx < len(chunks) - 1:
                await asyncio.sleep(AI_BATCH_COOLDOWN)

        except Exception as e:
            print(f"  {Color.RED}⚠️ 翻译批次 {idx + 1} 失败: {e}{Color.RESET}")

    # ── 3. 覆盖率校验：缺失的并发补译 ──
    missing = [t for t in tweets if str(t["tweet_id"]) not in translations]
    if missing:
        print(f"  {Color.YELLOW}⚠️ {len(missing)} 条推文缺少翻译，正在并发补译...{Color.RESET}")

        # 添加信号量限制补译时的突发并发，防止大量请求瞬间打满服务商限流
        sem = asyncio.Semaphore(5)

        async def _translate_one(t):
            tid = str(t["tweet_id"])
            async with sem:
                try:
                    resp = await asyncio.to_thread(
                        call_ai_with_retry,
                        messages=[
                            {"role": "system", "content": "你是一个精确的翻译。将以下推文翻译为中文。如果是纯中文则输出原句。只输出翻译结果，不要任何解释。"},
                            {"role": "user", "content": t["text"]},
                        ],
                        temperature=0.2,
                        model_override=AI_MODEL_TRANSLATE,
                    )
    
                    return tid, resp.choices[0].message.content.strip()
                except Exception:
                    return tid, "SKIP" # 失败时记录为 SKIP

        results = await asyncio.gather(*[_translate_one(t) for t in missing[:30]])
        for tid, trans in results:
            translations[tid] = trans
            raw_cache[tid] = trans
        save_json(cache_file, raw_cache)

    print(f"  {Color.GREEN}✓ 翻译完成：{len(translations)} 条{Color.RESET}")
    return translations
