"""
配置解析器 — 从 .env / 环境变量读取所有参数，不含硬编码默认值
"""

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

# ── AI 供应商降级链 ──────────────────────────────────────────
AI_PROVIDER_CHAIN = [
    p.strip().upper()
    for p in os.getenv("AI_PROVIDER_CHAIN", "").split(",")
    if p.strip()
]


def _add_provider_fallbacks(
    provider_name: str, api_key: str, base_url: str, env_prefix: str
):
    """动态加载某个供应商的所有备选模型"""
    suffixes = ["", "_2", "_3", "_4", "_5"]
    for idx, suffix in enumerate(suffixes, 1):
        model = os.getenv(f"{env_prefix}_FALLBACK_MODEL{suffix}")
        if model:
            AI_FALLBACK_PROVIDERS.append({
                "name": f"{provider_name}(备选{idx})",
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
            })


AI_FALLBACK_PROVIDERS: list[dict] = []

for _i, _prefix in enumerate(AI_PROVIDER_CHAIN):
    _key = os.getenv(f"{_prefix}_API_KEY")
    if not _key:
        continue
    _url = os.getenv(f"{_prefix}_BASE_URL", "")
    _model = os.getenv(f"{_prefix}_MODEL", "")
    _name = os.getenv(f"{_prefix}_NAME", _prefix)

    if _i == 0:
        AI_API_KEY = _key
        AI_BASE_URL = _url
        AI_MODEL = _model
    else:
        AI_FALLBACK_PROVIDERS.append({
            "name": _name,
            "api_key": _key,
            "base_url": _url,
            "model": _model,
            "is_primary": True,
        })
    _add_provider_fallbacks(_name, _key, _url, _prefix)

if "AI_API_KEY" not in dir():
    AI_API_KEY = None
    AI_BASE_URL = ""
    AI_MODEL = ""

# ── 任务特定模型支持 ──────────────────────────────────
# 允许为不同性质的任务指定不同的模型
AI_MODEL_TRANSLATE = os.getenv("AI_MODEL_TRANSLATE", AI_MODEL)
AI_MODEL_INSIGHTS = os.getenv("AI_MODEL_INSIGHTS", AI_MODEL)
