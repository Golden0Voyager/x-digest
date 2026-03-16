"""
规则化预过滤：零 LLM 调用

在翻译之前执行，用确定性规则过滤掉明显垃圾：
- RT 去重：相同内容的 RT 与原推只保留一条
- 内容质量门槛：有效文本过短、纯 emoji、截断链接推文
- 语言/垃圾过滤：日文内容、广告关键词
"""

import re
from difflib import SequenceMatcher

from pipeline import Color

# ── 预编译正则 ──────────────────────────────────────────────

# URL（含 t.co 和一般链接）
_URL_RE = re.compile(r"https?://\S+")
# @mention
_MENTION_RE = re.compile(r"@\w+")
# emoji（覆盖常见 Unicode emoji 范围）
_EMOJI_RE = re.compile(
    r"[\U0001F600-\U0001F64F"  # emoticons
    r"\U0001F300-\U0001F5FF"   # misc symbols
    r"\U0001F680-\U0001F6FF"   # transport
    r"\U0001F1E0-\U0001F1FF"   # flags
    r"\U00002702-\U000027B0"   # dingbats
    r"\U0000FE00-\U0000FE0F"   # variation selectors
    r"\U0001F900-\U0001F9FF"   # supplemental
    r"\U0001FA00-\U0001FA6F"   # extended-A
    r"\U0001FA70-\U0001FAFF"   # extended-B
    r"\U00002600-\U000026FF"   # misc symbols
    r"\U0000200D"              # zero width joiner
    r"\U0000231A-\U0000231B"   # watch/hourglass
    r"]+",
)
# RT 前缀
_RT_PREFIX_RE = re.compile(r"^RT @\w+:\s*")
# 日文字符（平假名、片假名、部分日文汉字特征）
_JAPANESE_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF\uFF65-\uFF9F]")
# 日文广告关键词
_JP_AD_KEYWORDS = [
    "キャンペーン", "PR", "プレゼント", "発売中", "予約受付",
    "お得な", "セール", "割引", "クーポン", "応募",
    "リツイートで", "フォロー&", "当選", "懸賞",
]
# 截断链接推文模式
_TRUNCATED_LINK_RE = re.compile(
    r"^(learn more|read more|check out|see more|details|link|more info)\s*[:：]?\s*$",
    re.IGNORECASE,
)

# ── 有效文本长度阈值 ──
_MIN_EFFECTIVE_LEN = 20


def _strip_to_effective(text: str) -> str:
    """去除 URL、emoji、@mention 后的有效文本"""
    t = _URL_RE.sub("", text)
    t = _MENTION_RE.sub("", t)
    t = _EMOJI_RE.sub("", t)
    return t.strip()


def _extract_rt_body(text: str) -> str | None:
    """提取 RT 的正文部分（去掉 'RT @user: ' 前缀）"""
    m = _RT_PREFIX_RE.match(text)
    if m:
        return text[m.end():].strip()
    return None


def _text_similarity(a: str, b: str) -> float:
    """快速文本相似度（SequenceMatcher）"""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _is_japanese_spam(text: str) -> bool:
    """检测日文垃圾内容"""
    jp_chars = _JAPANESE_RE.findall(text)
    # 日文字符占比 > 30%
    effective = _strip_to_effective(text)
    if effective and len(jp_chars) / len(effective) > 0.3:
        return True
    # 日文广告关键词匹配
    for kw in _JP_AD_KEYWORDS:
        if kw in text:
            return True
    return False


def curate(tweets: list[dict]) -> list[dict]:
    """
    规则化预过滤。

    返回通过筛选的推文列表（新列表，不修改原数据）。
    """
    if not tweets:
        return []

    stats = {"rt_dedup": 0, "short": 0, "truncated": 0, "japanese": 0, "content_dedup": 0}
    total = len(tweets)

    # ── 1. RT 去重 ──
    # 索引所有非 RT 推文的文本，用于相似度比对
    non_rt_texts: dict[str, str] = {}
    for t in tweets:
        if not t.get("is_retweet"):
            non_rt_texts[str(t["tweet_id"])] = t["text"].strip()

    # 记录已见过的 RT 正文（用于 RT 间去重）
    seen_rt_bodies: list[str] = []

    kept: list[dict] = []

    for t in tweets:
        tid = str(t["tweet_id"])
        text = t["text"].strip()

        # ── 1a. RT 去重逻辑 ──
        rt_body = _extract_rt_body(text)
        if t.get("is_retweet") or rt_body is not None:
            body = rt_body if rt_body else text
            # 检查是否有相同/高度相似的原推
            dup_with_original = False
            for orig_text in non_rt_texts.values():
                if _text_similarity(body, orig_text) > 0.8:
                    dup_with_original = True
                    break
            if dup_with_original:
                stats["rt_dedup"] += 1
                continue

            # 检查是否与已保留的 RT 重复
            dup_with_rt = False
            for seen in seen_rt_bodies:
                if _text_similarity(body, seen) > 0.8:
                    dup_with_rt = True
                    break
            if dup_with_rt:
                stats["rt_dedup"] += 1
                continue

            seen_rt_bodies.append(body)
            # 保留 RT 但去除前缀（原推不在本批时）
            if rt_body:
                t = {**t, "text": body}

        # ── 2. 内容质量门槛 ──
        effective = _strip_to_effective(text)

        # 有效文本过短
        if len(effective) < _MIN_EFFECTIVE_LEN:
            stats["short"] += 1
            continue

        # 截断链接推文
        if _TRUNCATED_LINK_RE.match(effective):
            stats["truncated"] += 1
            continue

        # ── 3. 日文垃圾过滤 ──
        if _is_japanese_spam(text):
            stats["japanese"] += 1
            continue

        kept.append(t)

    # ── 4. 跨账号内容去重 ──
    # 不同账号转发/改写同一新闻，比对 effective text 前 120 字符
    _CROSS_DEDUP_PREFIX = 120
    _CROSS_DEDUP_THRESHOLD = 0.55

    deduped: list[dict] = []
    for t in kept:
        eff = _strip_to_effective(t["text"].strip())[:_CROSS_DEDUP_PREFIX]
        is_dup = False
        dup_idx = -1
        for i, d in enumerate(deduped):
            d_eff = _strip_to_effective(d["text"].strip())[:_CROSS_DEDUP_PREFIX]
            if _text_similarity(eff, d_eff) > _CROSS_DEDUP_THRESHOLD:
                is_dup = True
                dup_idx = i
                break
        if is_dup:
            # 保留文本更长的那条
            if len(t["text"]) > len(deduped[dup_idx]["text"]):
                deduped[dup_idx] = t
            stats["content_dedup"] += 1
        else:
            deduped.append(t)

    kept = deduped

    filtered = total - len(kept)
    print(f"\n{Color.BOLD}━━━ 预过滤统计 ━━━{Color.RESET}")
    print(f"  输入: {total} 条")
    print(f"  {Color.RED}过滤: {filtered} 条{Color.RESET}")
    if stats["rt_dedup"]:
        print(f"    - RT 去重: {stats['rt_dedup']}")
    if stats["short"]:
        print(f"    - 内容过短: {stats['short']}")
    if stats["truncated"]:
        print(f"    - 截断链接: {stats['truncated']}")
    if stats["japanese"]:
        print(f"    - 日文垃圾: {stats['japanese']}")
    if stats["content_dedup"]:
        print(f"    - 跨账号去重: {stats['content_dedup']}")
    print(f"  {Color.GREEN}保留: {len(kept)} 条{Color.RESET}")

    return kept
