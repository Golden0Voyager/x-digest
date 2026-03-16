"""
Step 5: 纯 Python Markdown 拼装

零 LLM 调用，确定性输出：相同输入 → 相同输出。
"""

import json
import re
from pathlib import Path

from pipeline import Color

CUSTOM_ACCOUNTS_FILE = Path("custom_accounts.json")

# 质量门控阈值
_MIN_QUALITY = 3

# 预编译：去除推文中的所有 t.co 短链（Twitter 跟踪链接，在 Markdown 中无用）
_TCO_RE = re.compile(r"https://t\.co/[a-zA-Z0-9]+")

DISPLAY_CATEGORIES = [
    ("【核心头条】", ["核心头条", "核心"]),
    ("【AI & 算法】", ["AI", "算法"]),
    ("【芯片 & 硬件】", ["芯片", "硬件"]),
    ("【航天 & 自动驾驶】", ["航天", "自动驾驶"]),
    ("【市场 & 投资】", ["市场", "投资"]),
    ("【政治 & 政策】", ["政治", "政策"]),
    ("【F1 赛车围场】", ["F1", "赛车"]),
    ("【当代艺术】", ["艺术", "画廊", "美术馆"]),
]


def _load_bios() -> dict:
    """从 custom_accounts.json 加载所有账号的 bio"""
    if not CUSTOM_ACCOUNTS_FILE.exists():
        return {}
    try:
        raw = json.loads(CUSTOM_ACCOUNTS_FILE.read_text(encoding="utf-8"))
        bios = {}
        for val in raw.values():
            if isinstance(val, dict):
                bios.update(val)
        return bios
    except Exception:
        return {}


def _clean_tco(text: str) -> str:
    """去除所有 t.co 链接，清理多余空白并移除多余换行"""
    cleaned = _TCO_RE.sub("", text)
    # 将推文内部的多余换行转换为单空格或简单的换行，确保加粗斜体不破碎
    cleaned = cleaned.replace("\n\n", "\n").replace("\r", "")
    # 清理残留的空行和多余空格
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()



def assemble(
    tweets: list[dict],
    translations: dict,
    insights: dict,
    shortlinks: dict,
) -> tuple[str, str]:
    """
    纯 Python 拼装最终 Markdown。

    返回 (markdown_content, counts_summary)
    """
    if not tweets:
        return "", ""

    bios = _load_bios()

    category_items: dict[str, list] = {name: [] for name, _ in DISPLAY_CATEGORIES}
    fallback_items: list[str] = []

    for t in tweets:
        tid = str(t["tweet_id"])
        insight = insights.get(tid)
        if not insight:
            continue

        # ── 质量门控 ──
        quality = insight.get("quality", 3)
        if quality < _MIN_QUALITY:
            continue

        thought = insight.get("thought", "")
        if thought.upper() == "SKIP":
            continue

        username = t["username"]
        # 原文清理 t.co 链接，避免干扰加粗斜体格式
        original_text = _clean_tco(t["text"].strip())

        tweet_url = f"https://x.com/{username}/status/{tid}"
        bio = bios.get(username, "博主信息暂无")

        # 组装单条 Markdown（quality=5 加高亮标记）
        highlight = "🔥 " if quality == 5 else ""
        entry = f"{highlight}**@{username}** ({bio})\n\n"
        if original_text:
            entry += f"🔗 [原推]({tweet_url})：***{original_text}***\n"
        else:
            # 即使原文为空（纯图），也保留链接
            entry += f"🔗 [原推]({tweet_url})\n"

        # 展示推文附图（紧跟正文/链接）
        images = t.get("images", [])
        if images:
            entry += " ".join(f"![推文配图]({url})" for url in images) + "\n"
        
        entry += "\n" # 增加段落间距

        trans = translations.get(tid, "SKIP")
        if trans and trans.upper() != "SKIP":
            # 译文中清除 t.co 链接，保持干净
            trans = _clean_tco(trans)
            entry += f"📝 **译文**：{trans}\n\n"

        if thought:
            thought = thought.replace("启发性思考：", "").replace("启发 & 思考：", "").replace("💡", "").strip()
            if thought:
                entry += f"💡 **启示**：{thought}"

        # 归类：AI 分类直接匹配展示分类，无白名单限制
        cat_val = insight.get("category", "其他动态")
        matched = False
        for section_name, keywords in DISPLAY_CATEGORIES:
            if any(kw in cat_val for kw in keywords):
                category_items[section_name].append(entry)
                matched = True
                break

        if not matched:
            fallback_items.append(entry)

    # 拼装最终 Markdown
    sections: list[str] = []
    counts: list[str] = []

    for section_name, _ in DISPLAY_CATEGORIES:
        items = category_items[section_name]
        if items:
            sections.append(f"### {section_name}")
            sections.append("\n\n---\n\n".join(items))
            sections.append("\n")
            counts.append(f"• {section_name}: {len(items)} 条")

    if fallback_items:
        sections.append("### 【其他动态】")
        sections.append("\n\n---\n\n".join(fallback_items))
        counts.append(f"• 其他动态: {len(fallback_items)} 条")

    return "\n\n".join(sections), "\n".join(counts)
