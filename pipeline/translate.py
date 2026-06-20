"""
Step 2: 专注翻译

LLM 只做一件事 —— 将英文推文翻译为中文。
输出 JSON，逐批处理，缺失补译。
"""

import asyncio
import json
from pathlib import Path

from config import AI_BATCH_COOLDOWN, AI_BATCH_SIZE, AI_MAX_BATCH_SIZE, AI_MODEL_TRANSLATE
from pipeline import Color, call_ai_with_retry, extract_json, load_json, save_json

TRANSLATE_PROMPT = """\
你是专业翻译官。将以下 X (Twitter) 推文翻译为中文。

### 核心规则：
1. **翻译判定**：只要原文包含英文单词或句子（哪怕只有 1-2 个词，如 "Wow", "Exactly"），就必须翻译。
2. **跳过判定**：只有当原文是【纯中文】、【纯表情符号】或【纯数字/符号】时，才输出 "SKIP"。
3. **处理 RT (转发)**：对于 "RT @username: content" 格式，请翻译后面的 content 部分。
4. **术语保留**：保留 AI/科技领域的专有名词（如 GPU, LLM, Transformer, Sora, RAG）。
5. **链接清理**：移除原文中的所有 t.co 链接，不要在译文中体现。
6. **格式一致**：严格输出 JSON 数组，确保输入中的每个 ID 都在输出中出现。

### 格式要求（必须严格遵守）：
- 输出必须是合法的 JSON 数组
- 每个元素格式为：{"id": "原始ID", "translation": "翻译结果或SKIP"}
- 数组首尾用方括号 [] 包裹
- 元素之间用逗号分隔
- 不要包含任何 Markdown 代码块标记（如 ```json）
- 不要添加任何解释文字或注释

### 正确示例：
输入：
[{"id": "1", "text": "RT @ylecun: Proud to be part of the adventure!"}, {"id": "2", "text": "Next-gen H100 is shipping soon."}]

输出：
[{"id": "1", "translation": "转发自 @ylecun: 为能成为这段冒险的一部分而自豪！"}, {"id": "2", "translation": "下一代 H100 即将出货。"}]

### 错误示例（绝对不要这样输出）：
❌ 包含解释文字：Here is the translation: [{"id": "1"...
❌ Markdown 代码块：```json [{"id": "1"...
❌ 缺少逗号：[{"id": "1" "translation": ...} {"id": "2"...]
❌ 括号不匹配：[{"id": "1", "translation": "..."}
❌ 字段名错误：{"ID": "1", "text": "..."}
❌ 输出纯文本列表：1. ... 2. ...

### 特殊场景处理：
- 纯中文：{"id": "3", "text": "今天天气不错"} → {"id": "3", "translation": "SKIP"}
- 纯英文：{"id": "4", "text": "Amazing!"} → {"id": "4", "translation": "太棒了！"}
- 混合内容：{"id": "5", "text": "AI first mindset is crucial"} → {"id": "5", "translation": "AI优先思维至关重要"}
- RT 格式：{"id": "6", "text": "RT @elonmusk: Mars soon!"} → {"id": "6", "translation": "转发自 @elonmusk: 火星很快就要来了！"}

再次强调：只输出合法的 JSON 数组，不要任何其他内容。"""


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

    # ── 2. 分批处理（受 AI_MAX_BATCH_SIZE 保护，防止输出截断） ──
    safe_batch_size = min(AI_BATCH_SIZE, AI_MAX_BATCH_SIZE)
    if AI_BATCH_SIZE > AI_MAX_BATCH_SIZE:
        print(f"  {Color.YELLOW}⚠️ AI_BATCH_SIZE={AI_BATCH_SIZE} 超过安全上限 {AI_MAX_BATCH_SIZE}，已自动限制{Color.RESET}")
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
                max_tokens=4000,
            )
            items = extract_json(response.choices[0].message.content)
            returned_ids = set()
            for item in items:
                tid = str(item.get("id", ""))
                if tid:
                    returned_ids.add(tid)
                    translations[tid] = item.get("translation", "SKIP")

            # 单批次覆盖率审计
            missing = len(chunk) - len(returned_ids)
            if missing > 0:
                print(f"    {Color.YELLOW}⚠️ 批次覆盖率: 输入 {len(chunk)} / 返回 {len(returned_ids)} / 缺失 {missing}（将在末尾并发补译）{Color.RESET}")
            else:
                print(f"    {Color.GREY}✓ 批次覆盖率: 输入 {len(chunk)} / 返回 {len(returned_ids)}{Color.RESET}")

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
                        max_tokens=2048,
                    )

                    return tid, resp.choices[0].message.content.strip()
                except Exception:
                    return tid, "SKIP" # 失败时记录为 SKIP

        results = await asyncio.gather(*[_translate_one(t) for t in missing[:AI_MAX_BATCH_SIZE]])
        for tid, trans in results:
            translations[tid] = trans
            raw_cache[tid] = trans
        save_json(cache_file, raw_cache)

    print(f"  {Color.GREEN}✓ 翻译完成：{len(translations)} 条{Color.RESET}")
    return translations
