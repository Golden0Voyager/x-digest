"""
LLM 调用计数与 Token 消费追踪

提供全局单例 tracker，在每次 LLM 调用后记录：
  - endpoint（API 端点 host，如 token.sensenova.cn / api.sensenova.cn）
  - model（模型名）
  - prompt_tokens / completion_tokens / total_tokens
  - 调用次数

管道结束时通过 print_summary() 输出汇总报告，便于审计 Token Plan
配额消耗与降级链中各供应商的实际负载分布。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class UsageRecord:
    """单个 (endpoint, model) 组合的累积用量"""
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    failures: int = 0  # 调用失败次数（被降级或最终抛出）
    # finish_reason 分布：{"stop": N, "length": M, ...}
    # length = 被 max_tokens 截断（最危险，需立刻调小批次或调高 max_tokens）
    finish_reasons: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def truncated_calls(self) -> int:
        """因输出 token 上限被截断的调用次数"""
        return self.finish_reasons.get("length", 0)


class UsageTracker:
    """全局 LLM 调用追踪器（线程不安全，但管道内基本是顺序/asyncio.to_thread）"""

    def __init__(self):
        # key = "endpoint|model"，便于排序与展示
        self._records: dict[str, UsageRecord] = defaultdict(UsageRecord)

    @staticmethod
    def _extract_endpoint(base_url: str | None) -> str:
        """从 base_url 提取 host，未提供时标记为 default"""
        if not base_url:
            return "default"
        try:
            host = urlparse(base_url).hostname or base_url
            return host
        except Exception:
            return base_url

    def track(
        self,
        model: str,
        base_url: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        finish_reason: str | None = None,
    ) -> None:
        """记录一次成功调用"""
        endpoint = self._extract_endpoint(base_url)
        key = f"{endpoint}|{model}"
        rec = self._records[key]
        rec.calls += 1
        rec.prompt_tokens += prompt_tokens or 0
        rec.completion_tokens += completion_tokens or 0
        if finish_reason:
            rec.finish_reasons[finish_reason] = rec.finish_reasons.get(finish_reason, 0) + 1

    def track_failure(self, model: str, base_url: str | None) -> None:
        """记录一次失败调用（不影响 token 累计，但计入失败次数）"""
        endpoint = self._extract_endpoint(base_url)
        key = f"{endpoint}|{model}"
        self._records[key].failures += 1

    def reset(self) -> None:
        """清空所有记录（用于测试或多任务隔离）"""
        self._records.clear()

    def summary_lines(self) -> list[str]:
        """生成格式化的汇总报告（不带颜色，便于写日志）"""
        if not self._records:
            return ["（本次运行未发生 LLM 调用）"]

        # 按调用次数降序
        sorted_items = sorted(
            self._records.items(),
            key=lambda kv: kv[1].calls,
            reverse=True,
        )

        # 计算列宽
        endpoint_w = max(len("Endpoint"), max(len(k.split("|")[0]) for k in self._records))
        model_w = max(len("Model"), max(len(k.split("|")[1]) for k in self._records))

        lines = []
        header = (
            f"{'Endpoint':<{endpoint_w}}  "
            f"{'Model':<{model_w}}  "
            f"{'Calls':>6}  "
            f"{'Prompt':>10}  "
            f"{'Output':>10}  "
            f"{'Total':>10}  "
            f"{'Fails':>5}"
        )
        lines.append(header)
        lines.append("-" * len(header))

        total_calls = 0
        total_prompt = 0
        total_completion = 0
        total_failures = 0

        for key, rec in sorted_items:
            endpoint, model = key.split("|", 1)
            lines.append(
                f"{endpoint:<{endpoint_w}}  "
                f"{model:<{model_w}}  "
                f"{rec.calls:>6}  "
                f"{rec.prompt_tokens:>10,}  "
                f"{rec.completion_tokens:>10,}  "
                f"{rec.total_tokens:>10,}  "
                f"{rec.failures:>5}"
            )
            total_calls += rec.calls
            total_prompt += rec.prompt_tokens
            total_completion += rec.completion_tokens
            total_failures += rec.failures

        lines.append("-" * len(header))
        lines.append(
            f"{'TOTAL':<{endpoint_w}}  "
            f"{'':<{model_w}}  "
            f"{total_calls:>6}  "
            f"{total_prompt:>10,}  "
            f"{total_completion:>10,}  "
            f"{total_prompt + total_completion:>10,}  "
            f"{total_failures:>5}"
        )

        # Token Plan 配额提示（仅当检测到 token.sensenova.cn 时显示）
        tp_calls = sum(
            rec.calls
            for key, rec in self._records.items()
            if key.split("|")[0] == "token.sensenova.cn"
        )
        if tp_calls > 0:
            lines.append("")
            lines.append(
                f"[Token Plan 配额提示] 本次共调用 token.sensenova.cn {tp_calls} 次 "
                f"(按次计费，每 5h 重置：sensenova-6.7-flash-lite=1500/5h, "
                f"deepseek-v4-flash=150/5h)"
            )

        # finish_reason 分布（决定调大/调小批次的核心信号）
        all_reasons: dict[str, int] = {}
        total_truncated = 0
        for rec in self._records.values():
            for reason, count in rec.finish_reasons.items():
                all_reasons[reason] = all_reasons.get(reason, 0) + count
            total_truncated += rec.truncated_calls

        if all_reasons:
            reason_str = ", ".join(f"{k}={v}" for k, v in sorted(all_reasons.items(), key=lambda x: -x[1]))
            lines.append("")
            lines.append(f"[Finish Reasons] {reason_str}")

            if total_truncated > 0:
                # 列出哪些模型被截断（便于精准调批次）
                truncated_models = [
                    f"{key.split('|')[1]} (×{rec.truncated_calls})"
                    for key, rec in self._records.items()
                    if rec.truncated_calls > 0
                ]
                lines.append(
                    f"[!! 截断告警] {total_truncated} 次调用因 max_tokens 被截断: "
                    f"{', '.join(truncated_models)} → 建议调小 AI_BATCH_SIZE_TP 或调高对应 max_tokens"
                )

        return lines

    def print_summary(self, header: str = "LLM 用量汇总") -> None:
        """彩色打印到终端 + 写入日志"""
        # 延迟 import 避免循环依赖
        from pipeline import Color, log_print

        log_print(f"\n{Color.BOLD}━━━ {header} ━━━{Color.RESET}")
        # 检查是否有截断，截断行用红色高亮
        has_truncation = any(rec.truncated_calls > 0 for rec in self._records.values())
        for line in self.summary_lines():
            if line.startswith("[!! 截断告警]"):
                log_print(f"  {Color.RED}{Color.BOLD}{line}{Color.RESET}", "warning")
            elif line.startswith("[Finish Reasons]") and has_truncation:
                log_print(f"  {Color.YELLOW}{line}{Color.RESET}")
            else:
                log_print(f"  {Color.GREY}{line}{Color.RESET}")

    def summary_for_webhook(self) -> str:
        """生成精简版 lark_md 格式诊断块，用于飞书卡片底部追加（调试阶段）

        格式示例：
            ▫️ 调用：5 次 (TP:4 / 主链:1) · Token：125.8K (in 74.5K / out 51.3K)
            ▫️ finish: stop=4, length=1
            <font color='red'>⚠️ 截断: sensenova-6.7-flash-lite (×1) → 建议调小 AI_BATCH_SIZE_TP</font>
        """
        if not self._records:
            return "▫️ （本次未发生 LLM 调用）"

        # 1. 聚合各项指标
        total_calls = sum(rec.calls for rec in self._records.values())
        total_prompt = sum(rec.prompt_tokens for rec in self._records.values())
        total_completion = sum(rec.completion_tokens for rec in self._records.values())
        total_failures = sum(rec.failures for rec in self._records.values())

        tp_calls = sum(
            rec.calls for key, rec in self._records.items()
            if key.split("|")[0] == "token.sensenova.cn"
        )
        main_calls = total_calls - tp_calls

        # finish_reason 分布
        all_reasons: dict[str, int] = {}
        for rec in self._records.values():
            for reason, count in rec.finish_reasons.items():
                all_reasons[reason] = all_reasons.get(reason, 0) + count

        # 截断细节
        truncated_models = [
            (key.split("|")[1], rec.truncated_calls)
            for key, rec in self._records.items()
            if rec.truncated_calls > 0
        ]

        # 2. 格式化数字（K 缩写）
        def fmt_k(n: int) -> str:
            if n >= 1000:
                return f"{n/1000:.1f}K"
            return str(n)

        # 3. 拼装 lark_md
        lines = []
        lines.append(
            f"▫️ 调用：**{total_calls} 次** (TP:{tp_calls} / 主链:{main_calls})"
            f" · Token：{fmt_k(total_prompt + total_completion)}"
            f" (in {fmt_k(total_prompt)} / out {fmt_k(total_completion)})"
        )

        if all_reasons:
            reason_str = ", ".join(f"{k}={v}" for k, v in sorted(all_reasons.items(), key=lambda x: -x[1]))
            lines.append(f"▫️ finish: {reason_str}")

        if total_failures > 0:
            lines.append(f"<font color='orange'>▫️ 失败调用: {total_failures} 次（已自动降级）</font>")

        if truncated_models:
            detail = ", ".join(f"{m} (×{c})" for m, c in truncated_models)
            lines.append(
                f"<font color='red'>⚠️ 截断: {detail} → 建议调小 AI_BATCH_SIZE_TP 或调高 max_tokens</font>"
            )

        # Token Plan 配额健康度提示
        if tp_calls > 0:
            tp_pct = (tp_calls / 1500) * 100  # 以 6.7-flash-lite 配额为基准
            lines.append(
                f"▫️ TP 配额消耗：{tp_calls}/1500 (~{tp_pct:.1f}%, 按 6.7-flash-lite 上限算)"
            )

        return "\n".join(lines)


# ── 全局单例 ─────────────────────────────────────────────
usage_tracker = UsageTracker()
