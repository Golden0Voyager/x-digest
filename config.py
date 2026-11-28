"""
配置解析器 — 从 .env / 环境变量读取所有参数，不含硬编码默认值
"""

import json
import os

from dotenv import load_dotenv

load_dotenv()

# ── 抓取参数 ──────────────────────────────────────────────
ACCOUNTS = {}
TWEETS_PER_ACCOUNT = int(os.getenv("TWEETS_PER_ACCOUNT", "30"))
HOURS_LOOKBACK = int(os.getenv("HOURS_LOOKBACK", "72"))
CACHE_RETENTION_HOURS = int(os.getenv("CACHE_RETENTION_HOURS", "168"))
LANGUAGE = os.getenv("LANGUAGE", "zh-CN")
ACCOUNT_SCAN_INTERVAL = int(os.getenv("ACCOUNT_SCAN_INTERVAL", "12"))

# ── AI 管道参数 ───────────────────────────────────────────
AI_BATCH_SIZE = int(os.getenv("AI_BATCH_SIZE", "15"))
AI_BATCH_COOLDOWN = int(os.getenv("AI_BATCH_COOLDOWN", "15"))
# 单批次最大条目数上限（防止输出 token 截断）
# 默认 30 适配 Groq Kimi K2 (max_output=16K)，除非使用输出上限更高的模型否则不建议调大
AI_MAX_BATCH_SIZE = int(os.getenv("AI_MAX_BATCH_SIZE", "30"))
# Token Plan 端点专用批次大小
# 洞察任务使用该值；模型输出上限由 AI_MODEL_MAX_TOKENS 单独控制。
AI_BATCH_SIZE_TP = int(os.getenv("AI_BATCH_SIZE_TP", "30"))

# ── AI 供应商降级链 ──────────────────────────────────────────
AI_PROVIDER_CHAIN = [
    p.strip().upper()
    for p in os.getenv("AI_PROVIDER_CHAIN", "").split(",")
    if p.strip()
]
AI_MODEL_MAX_TOKENS: dict[str, int] = json.loads(
    os.getenv("AI_MODEL_MAX_TOKENS", "") or "{}"
)


def _add_provider_fallbacks(
    provider_name: str, api_key: str, base_url: str, env_prefix: str
):
    """动态加载某个供应商的所有备选模型"""
    fallback_api_key = os.getenv(f"{env_prefix}_FALLBACK_API_KEY") or api_key
    fallback_base_url = os.getenv(f"{env_prefix}_FALLBACK_BASE_URL") or base_url
    suffixes = ["", "_2", "_3", "_4", "_5"]
    for idx, suffix in enumerate(suffixes, 1):
        model = os.getenv(f"{env_prefix}_FALLBACK_MODEL{suffix}")
        if model:
            AI_FALLBACK_PROVIDERS.append({
                "name": f"{provider_name}(备选{idx})",
                "api_key": fallback_api_key,
                "base_url": fallback_base_url,
                "model": model,
            })


AI_FALLBACK_PROVIDERS: list[dict] = []
AI_API_KEY: str | None = None
AI_BASE_URL: str = ""
AI_MODEL: str = ""
_PROVIDER_CONFIGS: dict[str, dict] = {}

# 已知供应商默认地址（CI 环境下未注入 BASE_URL 时的兜底）
_DEFAULT_BASE_URLS = {
    "SENSENOVA": "https://api.sensenova.cn/compatible-mode/v2",
    "SILICONFLOW": "https://api.siliconflow.cn/v1",
    "GROQ": "https://api.groq.com/openai/v1",
    "OPENROUTER": "https://openrouter.ai/api/v1",
    "DEEPSEEK": "https://api.deepseek.com/v1",
    "ZHIPUAI": "https://open.bigmodel.cn/api/paas/v4",
    "OPENAI": "https://api.openai.com/v1",
}

# 第一个拿到有效 key 的供应商作为任务首选；显式 AI_FALLBACK_CHAIN 可覆盖其余顺序。
for _prefix in AI_PROVIDER_CHAIN:
    _key = os.getenv(f"{_prefix}_API_KEY")
    if not _key:
        continue
    _url = os.getenv(f"{_prefix}_BASE_URL", "")
    if not _url and _prefix in _DEFAULT_BASE_URLS:
        _url = _DEFAULT_BASE_URLS[_prefix]
    _model = os.getenv(f"{_prefix}_MODEL", "")
    _name = os.getenv(f"{_prefix}_NAME", _prefix)
    _PROVIDER_CONFIGS[_prefix] = {
        "name": _name,
        "api_key": _key,
        "base_url": _url,
    }

    if AI_API_KEY is None:
        AI_API_KEY = _key
        AI_BASE_URL = _url
        AI_MODEL = _model
    else:
        AI_FALLBACK_PROVIDERS.append({
            "name": _name,
            "api_key": _key,
            "base_url": _url,
            "model": _model,
        })
    _add_provider_fallbacks(_name, _key, _url, _prefix)


def _build_explicit_fallback_chain(raw_chain: str) -> list[dict]:
    providers = []
    for idx, entry in enumerate(raw_chain.split(","), 1):
        entry = entry.strip()
        if not entry:
            continue
        prefix, separator, model = entry.partition(":")
        if not separator or not model:
            raise ValueError(f"AI_FALLBACK_CHAIN 条目格式应为 PREFIX:model，收到 {entry!r}")
        prefix = prefix.strip().upper()
        provider = _PROVIDER_CONFIGS.get(prefix)
        if provider is None:
            continue
        api_key = os.getenv(f"{prefix}_FALLBACK_API_KEY") or provider["api_key"]
        base_url = os.getenv(f"{prefix}_FALLBACK_BASE_URL") or provider["base_url"]
        providers.append({
            "name": f"{provider['name']}(备选{idx})",
            "api_key": api_key,
            "base_url": base_url,
            "model": model.strip(),
        })
    return providers


_explicit_fallback_chain = os.getenv("AI_FALLBACK_CHAIN", "").strip()
if _explicit_fallback_chain:
    AI_FALLBACK_PROVIDERS = _build_explicit_fallback_chain(_explicit_fallback_chain)

# ── 任务特定模型支持 ──────────────────────────────────
# 允许为不同性质的任务指定不同的模型；为空时使用首选供应商模型。
AI_MODEL_TRANSLATE = os.getenv("AI_MODEL_TRANSLATE", "") or AI_MODEL
AI_MODEL_INSIGHTS = os.getenv("AI_MODEL_INSIGHTS", "") or AI_MODEL

# ── SenseNova Token Plan（独立端点）────────────────────
# 文档：docs/api/sensenova-token-plan-usage.md
# 与传统 api.sensenova.cn 不同的服务：
#   - 端点：token.sensenova.cn/v1（非 api.sensenova.cn/compatible-mode/v2）
#   - 限速：每 5h 1500 次（vs 原 1 QPS）
#   - 鉴权：单独 Token Plan Key（可在控制台与原 Key 分别创建）
SENSENOVA_TP_BASE_URL = os.getenv(
    "SENSENOVA_TP_BASE_URL", "https://token.sensenova.cn/v1"
)
# API Key 留空时回退到 SENSENOVA_API_KEY，方便复用凭据
SENSENOVA_TP_API_KEY = (
    os.getenv("SENSENOVA_TP_API_KEY")
    or os.getenv("SENSENOVA_API_KEY")
    or ""
)

# ── CI 环境预检查 ────────────────────────────────────────
if os.getenv("GITHUB_ACTIONS") == "true":
    _missing = []
    if not AI_API_KEY:
        _missing.append("AI_API_KEY (如 SENSENOVA_API_KEY)")
    if not AI_BASE_URL:
        _missing.append("AI_BASE_URL (如 SENSENOVA_BASE_URL)")
    if not AI_MODEL:
        _missing.append("AI_MODEL (如 SENSENOVA_MODEL)")
    if _missing:
        print("\n[CI-DIAG] GitHub Actions 检测到以下关键环境变量未注入：")
        for m in _missing:
            print(f"  - {m}")
        print("[CI-DIAG] 请前往仓库 Settings → Secrets → Actions 中配置，并在 workflow 的 env 中传入。\n")
