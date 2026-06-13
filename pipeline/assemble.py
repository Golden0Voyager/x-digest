"""
Step 5: 纯 Python Markdown 拼装

零 LLM 调用，确定性输出：相同输入 → 相同输出。
"""

import json
import re
from pathlib import Path

from pipeline import Color

CUSTOM_ACCOUNTS_FILE = Path("custom_accounts.json")
DEFAULT_ACCOUNTS_FILE = Path("defaults/suggested_accounts.json")

# 质量门控阈值
_MIN_QUALITY = 80

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
    """从 custom_accounts.json 加载 bio，不存在则回退到 defaults/suggested_accounts.json"""
    files_to_try = [CUSTOM_ACCOUNTS_FILE, DEFAULT_ACCOUNTS_FILE]
    for file in files_to_try:
        if not file.exists():
            continue
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
            if not raw:
                continue
            sample_val = next(iter(raw.values()))
            if isinstance(sample_val, dict):
                # 分组结构: {"DomainA": {"user1": "bio", ...}, ...}
                bios = {}
                for val in raw.values():
                    if isinstance(val, dict):
                        bios.update(val)
                return bios
            else:
                # 扁平结构: {"user1": "bio", "user2": "bio", ...}
                return raw
        except Exception:
            continue
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
) -> tuple[str, str]:
    """
    纯 Python 拼装最终 Markdown。

    返回 (markdown_content, counts_summary)
    """
    if not tweets:
        return "", ""

    bios = _load_bios()

    # ── 归类装配 ──
    category_items: dict[str, list] = {name: [] for name, _ in DISPLAY_CATEGORIES}
    fallback_items: list[str] = []
    
    skipped_no_insight = 0

    for t in tweets:
        tid = str(t["tweet_id"])
        insight = insights.get(tid)
        if not insight:
            skipped_no_insight += 1
            continue

        quality = insight.get("quality", 0)
        thought = insight.get("thought", "")
        if thought.upper() == "SKIP":
            # 即使没有深度启示，也要归类展示推文内容
            thought = ""

        username = t["username"]
        original_text = _clean_tco(t["text"].strip())
        tweet_url = f"https://x.com/{username}/status/{tid}"
        bio = bios.get(username, "")

        # 组装单条 Markdown（quality>=95 加高亮标记）
        highlight = "🔥 " if quality >= 95 else ""
        bio_suffix = f" ({bio})" if bio and bio != "博主信息暂无" else ""
        entry = f"{highlight}**@{username}**{bio_suffix}\n\n"
        if original_text:
            entry += f"🔗 [原推]({tweet_url})：***{original_text}***\n"
        else:
            entry += f"🔗 [原推]({tweet_url})\n"

        images = t.get("images", [])
        if images:
            entry += " ".join(f"![推文配图]({url})" for url in images) + "\n"
        
        entry += "\n"

        trans = translations.get(tid, "SKIP")
        if trans and trans.upper() != "SKIP":
            trans = _clean_tco(trans)
            entry += f"📝 **译文**：{trans}\n\n"

        background = insight.get("background", "")
        if background and background.upper() != "SKIP":
            entry += f"💡 **小贴士**：{background.strip()}\n\n"

        if thought:
            thought = thought.replace("启发性思考：", "").replace("启发 & 思考：", "").replace("💡", "").strip()
            if thought:
                entry += f"🧠 **启示**：{thought}"
                
        # 归类
        cat_val = insight.get("category", "其他动态")
        matched = False
        for section_name, keywords in DISPLAY_CATEGORIES:
            if any(kw in cat_val for kw in keywords):
                category_items[section_name].append(entry)
                matched = True
                break

        if not matched:
            fallback_items.append(entry)

    if skipped_no_insight > 0:
        print(f"  {Color.YELLOW}⚠️ {skipped_no_insight} 条推文缺少洞察分析，已跳过{Color.RESET}")

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
