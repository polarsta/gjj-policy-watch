"""关键词命中与分类模块。

接口契约见 SPEC.md 第 5 节：
- is_hit / classify / extract_date
"""

from __future__ import annotations

import re

from .models import Announcement

# 关键词 -> 类别 映射（SPEC 第 5 节 detector 契约）：
# 缴存→deposit，提取→withdrawal，贷款/额度/首付→loan，利率→rate，其余→general
_KEYWORD_CATEGORY: dict[str, str] = {
    "缴存": "deposit",
    "缴存基数": "deposit",
    "提取": "withdrawal",
    "贷款": "loan",
    "贷款额度": "loan",
    "额度": "loan",
    "最高额度": "loan",
    "首付": "loan",
    "利率": "rate",
}

_CATEGORIES = ["deposit", "withdrawal", "loan", "rate", "general"]


def _full_text(announcement: Announcement) -> str:
    """拼接标题与摘要作为检测文本。"""
    return f"{announcement.title} {announcement.snippet}".strip()


def is_hit(announcement: Announcement, settings: dict) -> bool:
    """标题或 snippet 命中 settings["keywords"] 任一词即为命中。"""
    text = _full_text(announcement)
    keywords: list[str] = settings.get("keywords") or []
    return any(kw and kw in text for kw in keywords)


def classify(announcement: Announcement) -> list[str]:
    """按关键词映射返回命中类别子集。

    返回 ["deposit","withdrawal","loan","rate","general"] 的子集；
    未命中任何映射词但含"调整/优化/新政/通知"等政策泛词时归入 "general"。
    无任何命中时返回 ["general"]，保证分类结果非空。
    """
    text = _full_text(announcement)
    cats: list[str] = []
    for kw, cat in _KEYWORD_CATEGORY.items():
        if kw in text and cat not in cats:
            cats.append(cat)
    if not cats:
        # 泛政策词或其他情况归入 general
        cats = ["general"]
    # 按规范顺序输出，保证结果稳定可测
    return [c for c in _CATEGORIES if c in cats]


# 中文日期：2026年8月20日
_RE_CN_DATE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?")
# 连字符日期：2026-08-20 / 2026-8-2
_RE_DASH_DATE = re.compile(r"(20\d{2})-(\d{1,2})-(\d{1,2})")
# 点号日期：2026.8.20
_RE_DOT_DATE = re.compile(r"(20\d{2})\.(\d{1,2})\.(\d{1,2})")
# 斜杠日期：2026/8/20
_RE_SLASH_DATE = re.compile(r"(20\d{2})/(\d{1,2})/(\d{1,2})")

_DATE_PATTERNS = [_RE_CN_DATE, _RE_DASH_DATE, _RE_DOT_DATE, _RE_SLASH_DATE]


def extract_date(text: str | None) -> str | None:
    """从文本中解析日期，归一化为 ISO "YYYY-MM-DD"；失败返回 None。

    支持示例："2026年8月20日" -> "2026-08-20"、"2026-08-20"、"2026.8.20"。
    会校验月/日取值合法性。
    """
    if not text:
        return None
    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None
