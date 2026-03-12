"""
X-Digest 管道处理模块

提供共用的 AI 调用、JSON 工具和终端色彩常量。
"""

import json
import re
import time
from pathlib import Path

from openai import OpenAI

from config import AI_API_KEY, AI_BASE_URL, AI_MODEL, AI_FALLBACK_PROVIDERS


# ── 终端色彩 ──────────────────────────────────────────────

class Color:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    GREY = "\033[90m"
    RESET = "\033[0m"


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

    raise ValueError(f"无法从 LLM 响应中提取 JSON 数组: {text[:200]}...")


# ── AI 客户端（懒加载，按供应商缓存） ─────────────────────

_ai_clients: dict[str, OpenAI] = {}


def _get_client(api_key: str, base_url: str) -> OpenAI:
    cache_key = f"{base_url}"
    if cache_key not in _ai_clients:
        _ai_clients[cache_key] = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=180,
        )
    return _ai_clients[cache_key]


def call_ai_with_retry(messages, temperature=0.2, model_override=None):
    """带快速降级的 AI 调用。

    主模型 2 次尝试，备选模型各 1 次（每供应商共 3 次），
    全部供应商耗尽后抛出最后一个异常。
    
    model_override: 允许为特定任务覆盖主模型设置
    """
    primary_model = model_override if model_override else AI_MODEL
    providers = [
        {"name": "主模型", "api_key": AI_API_KEY, "base_url": AI_BASE_URL, "model": primary_model, "is_primary": True},
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
                )
                # 降级成功时提示当前实际服务的模型
                if i > 0 or attempt > 1:
                    print(f"  {Color.GREEN}✓ [{provider['name']}] {provider['model']} 响应成功{Color.RESET}")
                return result
            except Exception as e:
                last_error = e

                if attempt == max_attempts:
                    if i < len(providers) - 1:
                        next_name = providers[i + 1]["name"]
                        print(f"  {Color.YELLOW}⚠️ [{provider['name']}] 失败，降级到 [{next_name}]{Color.RESET}")
                    break

                # 仅主模型第 1 次失败时短暂等待后重试
                wait_sec = 3
                is_rate_limit = "RateLimitError" in type(e).__name__ or "rate" in str(e).lower()
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
