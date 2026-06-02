"""
DeepSeek 模型翻译能力对比测试

对比模型（SenseNova）：
  - DeepSeek-V3-1                          （基线 1：通用对话 32K）
  - DeepSeek-R1                            （基线 2：原生推理 8K，当前翻译专用）
  - DeepSeek-R1-Distill-Qwen-32B           （待测 1：蒸馏推理 8K，永久免费）
  - DeepSeek-R1-Distill-Qwen-14B           （待测 2：蒸馏推理 32K，永久免费）

测试样本：12 条真实推文风格样本，覆盖：
  - 硬核技术（GPU / LLM / MoE）
  - 金融（Fed Pivot / CPI / bps）
  - 缩写（GPU, LLM, RT, AGI, TPU, NVLink）
  - 中英混合 / 纯中文 / 纯表情
  - 长句 + 短句

评估指标：
  1. JSON 格式合规率（是否输出合法 JSON 数组）
  2. 术语保留度（关键英文术语是否保留）
  3. 翻译完成度（每条 ID 是否都有翻译）
  4. 响应时间 / token 消耗
  5. 纯中文 / 表情是否正确识别为 SKIP

运行：
  uv run python tests/test_translate_models.py
"""

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

BASE_URL = "https://api.sensenova.cn/compatible-mode/v2"

MODELS_TO_TEST = [
    "DeepSeek-V3-1",
    "DeepSeek-R1",
    "DeepSeek-R1-Distill-Qwen-32B",
    "DeepSeek-R1-Distill-Qwen-14B",
]

TRANSLATE_PROMPT = """\
你是专业翻译官。将以下 X (Twitter) 推文翻译为中文。

### 核心规则：
1. **翻译判定**：只要原文包含英文单词或句子（哪怕只有 1-2 个词），就必须翻译。
2. **跳过判定**：只有当原文是【纯中文】、【纯表情符号】或【纯数字/符号】时，才输出 "SKIP"。
3. **处理 RT (转发)**：对于 "RT @username: content" 格式，请翻译后面的 content 部分。
4. **术语保留**：保留 AI/科技/金融领域的专有名词（如 GPU, LLM, Transformer, MoE, H100, NVLink, CPI, Fed Pivot, bps, TPU, NVDA, Sora, RAG, AGI, TSMC, ROI）。
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

### 特殊场景处理：
- 纯中文：{"id": "3", "text": "今天天气不错"} → {"id": "3", "translation": "SKIP"}
- 纯英文：{"id": "4", "text": "Amazing!"} → {"id": "4", "translation": "太棒了！"}
- 混合内容：{"id": "5", "text": "AI first mindset is crucial"} → {"id": "5", "translation": "AI优先思维至关重要"}
- RT 格式：{"id": "6", "text": "RT @elonmusk: Mars soon!"} → {"id": "6", "translation": "转发自 @elonmusk: 火星很快就要来了！"}

再次强调：只输出合法的 JSON 数组，不要任何其他内容。"""


SAMPLE_TWEETS = [
    {
        "id": "1",
        "text": "The new Blackwell B200 GPU has 208B transistors and 1.8TB/s NVLink. Massive leap for LLM training.",
    },
    {
        "id": "2",
        "text": "Our MoE architecture now uses dynamic routing, reducing inference FLOPs by 40% while keeping accuracy.",
    },
    {
        "id": "3",
        "text": "Latest CPI data suggests the Fed Pivot could come in March. Market is pricing in 25bps cut.",
    },
    {
        "id": "4",
        "text": "RT @ylecun: Proud to be part of the adventure!",
    },
    {
        "id": "5",
        "text": "AGI is closer than most people think. The next 18 months will be wild.",
    },
    {
        "id": "6",
        "text": "TSMC's 2nm yield is now above 60%, beating Samsung and Intel. NVDA stock will benefit.",
    },
    {
        "id": "7",
        "text": "今天天气不错，适合出去走走 🚶",
    },
    {
        "id": "8",
        "text": "🚀🚀🚀",
    },
    {
        "id": "9",
        "text": "Sora can generate 60s 1080p video. This changes everything for content creators.",
    },
    {
        "id": "10",
        "text": "Apple's new M4 chip uses second-gen 3nm process, with 10-core CPU and 10-core GPU. Power efficiency is insane.",
    },
    {
        "id": "11",
        "text": "RAG is dead. Long context is all you need. /s",
    },
    {
        "id": "12",
        "text": "TPU v6 is shipping to cloud customers. Google just leveled up its AI infrastructure game.",
    },
]


TERMS_TO_PRESERVE = {
    "1": ["B200", "GPU", "NVLink", "LLM"],
    "2": ["MoE", "FLOPs"],
    "3": ["CPI", "Fed Pivot", "25bps"],
    "4": ["RT"],
    "5": ["AGI"],
    "6": ["TSMC", "2nm", "NVDA"],
    "9": ["Sora"],
    "10": ["M4", "3nm", "CPU", "GPU"],
    "11": ["RAG"],
    "12": ["TPU"],
}


@dataclass
class ModelResult:
    name: str
    raw_output: str = ""
    parsed: list = field(default_factory=list)
    elapsed_sec: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""
    parse_warning: str = ""


def extract_json(text: str) -> tuple[list, str]:
    """复用项目里的 extract_json 风格。返回 (items, warning)"""
    text = text.strip()
    try:
        return json.loads(text), ""
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip()), "markdown fence detected"
        except json.JSONDecodeError:
            pass
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1]), "bracket extraction"
        except json.JSONDecodeError:
            pass
    found = []
    for m in re.finditer(r'\{[^{}]*?"id"\s*:\s*".*?"[^{}]*?\}', text, re.DOTALL):
        try:
            found.append(json.loads(m.group(0)))
        except Exception:
            pass
    if found:
        return found, f"regex rescue: {len(found)} items"
    raise ValueError(f"无法提取 JSON: {text[:200]}")


async def call_model(client: OpenAI, model: str, prompt: str, payload: str) -> ModelResult:
    result = ModelResult(name=model)
    t0 = time.monotonic()
    try:
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": payload},
            ],
            temperature=0.2,
            max_tokens=4000,
        )
        result.elapsed_sec = time.monotonic() - t0
        result.raw_output = resp.choices[0].message.content
        if resp.usage:
            result.prompt_tokens = resp.usage.prompt_tokens
            result.completion_tokens = resp.usage.completion_tokens
        try:
            result.parsed, warn = extract_json(result.raw_output)
            result.parse_warning = warn
        except Exception as e:
            result.error = f"JSON 解析失败: {e}"
    except Exception as e:
        result.elapsed_sec = time.monotonic() - t0
        result.error = f"API 调用失败: {e}"
    return result


def evaluate_result(result: ModelResult) -> dict:
    metrics = {
        "json_ok": False,
        "json_warning": result.parse_warning or "",
        "id_coverage": 0,
        "expected_ids": len(SAMPLE_TWEETS),
        "term_preservation": {},
        "term_preservation_rate": 0.0,
        "skip_correct_ids": [],
    }
    if result.error:
        return metrics

    metrics["json_ok"] = True
    expected_ids = {t["id"] for t in SAMPLE_TWEETS}
    got_ids = {str(it.get("id", "")) for it in result.parsed}
    metrics["id_coverage"] = len(got_ids & expected_ids)

    # 术语保留度
    term_results = {}
    term_hit = 0
    term_total = 0
    for tid, terms in TERMS_TO_PRESERVE.items():
        item = next((it for it in result.parsed if str(it.get("id", "")) == tid), None)
        if not item:
            term_results[tid] = "MISSING"
            term_total += len(terms)
            continue
        trans = str(item.get("translation", ""))
        if trans.upper() == "SKIP":
            term_results[tid] = "SKIP"
            term_total += len(terms)
            continue
        missing = [t for t in terms if t not in trans]
        if missing:
            term_results[tid] = f"missing {missing}"
            term_total += len(terms)
        else:
            term_results[tid] = "OK"
            term_hit += len(terms)
            term_total += len(terms)
    metrics["term_preservation"] = term_results
    metrics["term_preservation_rate"] = term_hit / term_total if term_total else 0.0

    # SKIP 正确性
    for it in result.parsed:
        trans = str(it.get("translation", ""))
        if it.get("id") in ("7", "8") and trans.upper() == "SKIP":
            metrics["skip_correct_ids"].append(it["id"])

    return metrics


def print_section(title: str):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_model_table(results: list[tuple[ModelResult, dict]]):
    print(f"\n{'模型':<35} {'JSON':<6} {'覆盖率':<8} {'术语保留':<10} {'耗时(s)':<10} {'Tokens':<15} {'状态'}")
    print("-" * 110)
    for r, m in results:
        json_ok = "OK" if m["json_ok"] else "FAIL"
        cov = f"{m['id_coverage']}/{m['expected_ids']}"
        term_rate = f"{m['term_preservation_rate']*100:.0f}%"
        elapsed = f"{r.elapsed_sec:.1f}"
        tokens = f"{r.prompt_tokens}+{r.completion_tokens}"
        status = r.error[:40] if r.error else m.get("json_warning", "OK")
        print(f"{r.name:<35} {json_ok:<6} {cov:<8} {term_rate:<10} {elapsed:<10} {tokens:<15} {status}")


def print_translation_grid(results: list[tuple[ModelResult, dict]]):
    """横向对比每个样本在 4 个模型下的翻译结果"""
    print_section("逐条翻译对比（横向）")
    for tweet in SAMPLE_TWEETS:
        tid = tweet["id"]
        print(f"\n📌 [{tid}] 原文: {tweet['text']}")
        for r, m in results:
            item = next((it for it in r.parsed if str(it.get("id", "")) == tid), None)
            if not item:
                print(f"   {r.name:<35} → ❌ MISSING")
            else:
                trans = str(item.get("translation", ""))
                marker = "✅" if trans.upper() == "SKIP" and tweet["id"] in ("7", "8") else "→"
                print(f"   {r.name:<35} {marker} {trans[:120]}")


def print_term_audit(results: list[tuple[ModelResult, dict]]):
    print_section("术语保留审计（横向）")
    print(f"{'推文ID':<8}", end="")
    for r, _ in results:
        short = r.name.replace("DeepSeek-", "").replace("-Distill-", "-D-")
        print(f"{short:<22}", end="")
    print()
    print("-" * (8 + 22 * len(results)))
    for tweet in SAMPLE_TWEETS:
        tid = tweet["id"]
        terms = TERMS_TO_PRESERVE.get(tid, [])
        if not terms:
            continue
        print(f"{tid:<8}", end="")
        for r, m in results:
            cell = m["term_preservation"].get(tid, "-")
            short_cell = cell[:20]
            print(f"{short_cell:<22}", end="")
        print(f"  期望保留: {terms}")


def print_verdict(results: list[tuple[ModelResult, dict]]):
    print_section("📊 结论与建议")

    # 排序：术语保留率 + 覆盖率 综合（API 失败模型排到末尾）
    def score(m: dict) -> float:
        if not m["json_ok"]:
            return -1.0
        return m["term_preservation_rate"] * 0.6 + (m["id_coverage"] / max(m["expected_ids"], 1)) * 0.4

    ranked = sorted(results, key=lambda x: -score(x[1]))

    print("\n综合排名（术语保留 60% + 覆盖率 40%）：")
    for i, (r, m) in enumerate(ranked, 1):
        s = score(m)
        if s < 0:
            print(f"  {i}. {r.name:<35} ❌ API 失败 ({r.error[:60]})")
        else:
            print(f"  {i}. {r.name:<35} 综合分={s:.3f}  (术语 {m['term_preservation_rate']*100:.0f}% | 覆盖 {m['id_coverage']}/{m['expected_ids']})")

    print("\n翻译任务适配性判断（人工核对下方逐条对比后填写）：")
    print("  - DeepSeek-R1-Distill-Qwen-32B 是否可担任翻译？[  ]是 [  ]否")
    print("  - DeepSeek-R1-Distill-Qwen-14B 是否可担任翻译？[  ]是 [  ]否")
    print("  - 限流体感（1 QPS / 6 RPM）：_______")
    print("  - 性价比 vs DeepSeek-R1 原生：_______")


async def main():
    api_key = os.getenv("SENSENOVA_API_KEY")
    if not api_key:
        print("❌ 错误：请先设置 SENSENOVA_API_KEY 环境变量")
        return

    client = OpenAI(api_key=api_key, base_url=BASE_URL, timeout=180)
    payload = json.dumps([{"id": t["id"], "text": t["text"]} for t in SAMPLE_TWEETS], ensure_ascii=False)

    print_section("🧪 SenseNova DeepSeek 模型翻译能力对比")
    print(f"样本数: {len(SAMPLE_TWEETS)} 条")
    print(f"测试模型: {len(MODELS_TO_TEST)} 个")
    print(f"限流策略: 顺序调用（每调用间隔 ≥10s 防止触发 1 QPS）")
    print(f"预计耗时: ~{len(MODELS_TO_TEST) * 25}s")

    results: list[tuple[ModelResult, dict]] = []
    for i, model in enumerate(MODELS_TO_TEST):
        print(f"\n⏳ [{i+1}/{len(MODELS_TO_TEST)}] 正在调用 {model} ...")
        result = await call_model(client, model, TRANSLATE_PROMPT, payload)
        metrics = evaluate_result(result)
        results.append((result, metrics))
        if result.error:
            print(f"   ✗ 失败: {result.error[:120]}")
        else:
            print(f"   ✓ 完成 (耗时 {result.elapsed_sec:.1f}s, 覆盖 {metrics['id_coverage']}/{metrics['expected_ids']})")
        if i < len(MODELS_TO_TEST) - 1:
            await asyncio.sleep(12)  # 留足余量防限流

    print_section("📊 性能与质量总览")
    print_model_table(results)

    print_translation_grid(results)
    print_term_audit(results)
    print_verdict(results)


if __name__ == "__main__":
    asyncio.run(main())
