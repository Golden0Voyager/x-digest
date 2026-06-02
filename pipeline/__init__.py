"""
X-Digest 管道处理模块

提供共用的 AI 调用、JSON 工具和终端色彩常量。
"""

import json
import logging
import os
import re
import time
from pathlib import Path

import httpx
from openai import OpenAI

from config import AI_API_KEY, AI_BASE_URL, AI_MODEL, AI_FALLBACK_PROVIDERS


# ── 终端色彩 ──────────────────────────────────────────────

class Color:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    MATRIX_GREEN = "\033[38;5;46m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    GREY = "\033[90m"
    RESET = "\033[0m"


# ── 日志工具 ──────────────────────────────────────────────

logger = logging.getLogger("x_digest")

def log_print(msg, level="info"):
    """同时打印到屏幕并存入日志文件（自动剥离 ANSI 颜色代码）"""
    clean_msg = re.sub(r'\033\[\d+(;\d+)*m', '', str(msg))
    if level == "info": logger.info(clean_msg)
    elif level == "warning": logger.warning(clean_msg)
    elif level == "error": logger.error(clean_msg)
    print(msg)


# ── JSON 工具 ─────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_json(text: str) -> list:
    """从 LLM 响应中提取 JSON 数组。

    兼容以下情况：
    - 纯 JSON 数组
    - markdown 代码块包裹 (```json ... ```)
    - LLM 前后有多余文本 (找第一个 [ 到最后一个 ])
    - 响应被截断（缺少闭合 ]）：抢救已完成的条目
    """
    text = text.strip()
    # 1. 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. 去掉 markdown 代码块
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 3. 找第一个 [ 到最后一个 ]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    # 4. 强力抢救：使用正则提取每一个完整的 {} 对象
    # 匹配模式: {"id": "...", ... }
    # 注意：这种方式不完美，但能极大提高截断时的覆盖率
    found_objects = []
    # 匹配 {"id": "数字/字符串", ... } 结构的最小闭合块
    object_matches = re.finditer(r'\{[^{}]*?"id"\s*:\s*".*?"[^{}]*?\}', text, re.DOTALL)
    for m in object_matches:
        try:
            obj = json.loads(m.group(0))
            found_objects.append(obj)
        except: pass

    if found_objects:
        print(f"  {Color.YELLOW}⚠️ JSON 结构受损，正则抢救出 {len(found_objects)} 条记录{Color.RESET}")
        return found_objects

    # 5. 终极抢救：处理对象内部有嵌套结构的情况
    # 使用计数法匹配完整的 {...} 块
    found_objects = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 1
            j = i + 1
            in_string = False
            escape = False
            while j < len(text) and depth > 0:
                c = text[j]
                if escape:
                    escape = False
                elif c == '\\':
                    escape = True
                elif c == '"' and not escape:
                    in_string = not in_string
                elif not in_string:
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                j += 1
            if depth == 0:
                try:
                    obj = json.loads(text[i:j])
                    if isinstance(obj, dict) and 'id' in obj:
                        found_objects.append(obj)
                except:
                    pass
            i = j
        else:
            i += 1

    if found_objects:
        print(f"  {Color.YELLOW}⚠️ JSON 结构严重受损，深度解析抢救出 {len(found_objects)} 条记录{Color.RESET}")
        return found_objects

    raise ValueError(f"无法从 LLM 响应中提取 JSON 数组: {text[:200]}...")


# ── AI 客户端（懒加载，按供应商缓存） ─────────────────────

_ai_clients: dict[str, OpenAI] = {}


def _get_client(api_key: str, base_url: str) -> OpenAI:
    # 空字符串转为 None，避免 OpenAI 客户端解析异常
    if not base_url:
        base_url = None

    cache_key = f"{base_url or 'default'}:{api_key[:8]}"
    if cache_key not in _ai_clients:
        client_kwargs: dict = {
            "api_key": api_key,
            "base_url": base_url,
            "timeout": 180,
        }
        # CI / 服务器环境代理支持：优先读取 PROXY，其次标准环境变量
        proxy_url = (
            os.getenv("PROXY")
            or os.getenv("HTTPS_PROXY")
            or os.getenv("HTTP_PROXY")
            or os.getenv("ALL_PROXY")
        )
        if proxy_url:
            client_kwargs["http_client"] = httpx.Client(proxy=proxy_url, timeout=180)

        _ai_clients[cache_key] = OpenAI(**client_kwargs)
    return _ai_clients[cache_key]


def call_ai_with_retry(
    messages,
    temperature=0.2,
    model_override=None,
    max_tokens=4096,
    base_url_override=None,
    api_key_override=None,
):
    """带快速降级的 AI 调用。

    主模型 2 次尝试，备选模型各 1 次（每供应商共 3 次），
    全部供应商耗尽后抛出最后一个异常。

    model_override: 允许为特定任务覆盖主模型设置
    max_tokens: 最大输出 token 数，防止响应截断（默认 4096）
    base_url_override: 覆盖主供应商的 base_url（用于独立端点如 Token Plan）
    api_key_override: 覆盖主供应商的 api_key
    """
    primary_model = model_override if model_override else AI_MODEL
    providers = [
        {
            "name": "主模型",
            "api_key": api_key_override or AI_API_KEY,
            "base_url": base_url_override or AI_BASE_URL,
            "model": primary_model,
            "is_primary": True,
        },
        *AI_FALLBACK_PROVIDERS,
    ]

    last_error = None
    for i, provider in enumerate(providers):
        client = _get_client(provider["api_key"], provider["base_url"])
        max_attempts = 2 if provider.get("is_primary") else 1

        for attempt in range(1, max_attempts + 1):
            try:
                result = client.chat.completions.create(
                    model=provider["model"],
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                # token 用量统计
                if result.usage:
                    u = result.usage
                    print(f"  {Color.GREY}📊 Token: {u.prompt_tokens} in / {u.completion_tokens} out / {u.total_tokens} total{Color.RESET}")
                # 降级成功时提示当前实际服务的模型
                if i > 0 or attempt > 1:
                    print(f"  {Color.GREEN}✓ [{provider['name']}] {provider['model']} 响应成功{Color.RESET}")
                return result
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                err_type = type(e).__name__

                # 连接级别失败快速诊断
                if "connection" in err_type.lower() or "connect" in err_str:
                    p_url = provider.get("base_url", "")
                    if not p_url:
                        print(f"  {Color.RED}⚠️ [{provider['name']}] BASE_URL 为空，正在使用 OpenAI 默认地址，请确认该地址在当前网络可连通{Color.RESET}")
                    elif "127.0.0.1" in p_url or "localhost" in p_url:
                        print(f"  {Color.RED}⚠️ [{provider['name']}] BASE_URL 指向本地地址 ({p_url})，在 CI/服务器环境不可达。请检查环境变量注入或更换为公网 API 地址{Color.RESET}")
                    if os.getenv("GITHUB_ACTIONS") == "true":
                        print(f"  {Color.GREY}    提示：GitHub Actions 需在仓库 Settings → Secrets → Actions 中配置 {provider['name']} 相关环境变量{Color.RESET}")

                if attempt == max_attempts:
                    if i < len(providers) - 1:
                        next_name = providers[i + 1]["name"]
                        print(f"  {Color.YELLOW}⚠️ [{provider['name']}] 失败，降级到 [{next_name}]{Color.RESET}")
                    break

                # 硬配额耗尽 / 模型不存在 / 认证失败 → 立刻降级，无需等待
                is_hard_fail = any(k in err_str for k in [
                    "资源包余量已用尽", "quota", "3008",
                    "no endpoints found", "404",
                    "令牌已过期", "authentication", "401",
                ])
                if is_hard_fail:
                    print(f"  {Color.YELLOW}⚠️ [{provider['name']}] 调用失败: {e}{Color.RESET}")
                    break  # 直接跳出内层循环，进入下一个 provider

                # 仅主模型第 1 次失败时短暂等待后重试
                wait_sec = 3
                is_rate_limit = "RateLimitError" in err_type or "rate" in err_str
                if hasattr(e, "response") and hasattr(e.response, "headers"):
                    retry_after = e.response.headers.get("retry-after")
                    if retry_after:
                        wait_sec = min(int(float(retry_after)) + 1, 30)
                elif is_rate_limit:
                    wait_sec = 10
                print(f"  {Color.YELLOW}⚠️ [{provider['name']}] 调用失败: {e}{Color.RESET}")
                print(f"  {Color.GREY}⏳ {wait_sec}s 后重试...{Color.RESET}")
                time.sleep(wait_sec)

    raise last_error
