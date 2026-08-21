"""数据模型定义（dataclass），契约见 SPEC.md 第 4 节。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


def make_fingerprint(city: str, title: str, url: str) -> str:
    """生成公告指纹：md5(city + title + url)。

    用于 seen 去重，同一城市同一标题同一链接视为同一公告。
    """
    raw = f"{city}{title}{url}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()


@dataclass
class Announcement:
    """一条政策公告/搜索发现。"""

    city: str
    title: str
    url: str
    date: str | None            # ISO 格式 "YYYY-MM-DD" 或 None
    channel: str                # "watcher" | "search"
    snippet: str = ""
    fingerprint: str = ""       # md5(city+title+url)，为空时自动生成

    def __post_init__(self) -> None:
        # 标题/链接去首尾空白，避免指纹因空白差异而失效
        self.title = self.title.strip()
        self.url = self.url.strip()
        if not self.fingerprint:
            self.fingerprint = self.make_fingerprint()

    def make_fingerprint(self) -> str:
        """按 SPEC 规则计算本公告指纹。"""
        return make_fingerprint(self.city, self.title, self.url)


@dataclass
class ChangeEvent:
    """数据库字段变更事件（differ 输出）。"""

    city: str
    field_path: str             # 如 "loan.max_family"
    old_value: Any
    new_value: Any
    source_url: str
    detected_at: str            # ISO datetime


@dataclass
class ScanResult:
    """一次巡检（daily）的汇总结果。"""

    run_at: str
    announcements: list[Announcement] = field(default_factory=list)  # 新发现（已去重）
    hits: list[Announcement] = field(default_factory=list)           # 命中关键词的公告
    errors: list[str] = field(default_factory=list)
