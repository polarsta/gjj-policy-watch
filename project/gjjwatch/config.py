"""配置文件加载模块。

负责读取 config/settings.yaml 与 config/cities.yaml，
接口契约见 SPEC.md 第 3、5 节。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# 项目根目录（gjjwatch 包上一级），用于解析相对配置路径
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# settings.yaml 缺省值：配置文件缺失字段时兜底，保证下游模块取值不报错
_DEFAULT_SETTINGS: dict[str, Any] = {
    "date_window_days": 7,
    "request_timeout": 15,
    "request_delay": 1.0,
    "user_agent": "Mozilla/5.0 (compatible; gjj-policy-watch/1.0)",
    "keywords": [
        "缴存基数", "贷款额度", "最高额度", "提取", "利率",
        "首付", "调整", "优化", "新政", "通知",
    ],
    "search": {
        "backend": "bing_html",
        "results_per_query": 10,
        "policy_terms": ["贷款", "提取", "缴存", "利率", "首付"],
        "domain_boost": ["gov.cn"],
    },
    "llm": {
        "enabled": False,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "notify": {
        "console": True,
        "webhook_url": "",
        "smtp": {"enabled": False, "host": "", "port": 465, "user": "", "to": []},
    },
    "paths": {
        "db": "data/gjj_policy_database.json",
        "seen": "data/seen_announcements.json",
        "snapshots": "data/snapshots",
        "change_log": "data/change_log.json",
        "reports": "reports",
    },
}


def _resolve(path: str | Path) -> Path:
    """将相对路径解析为绝对路径（相对于项目根目录）。"""
    p = Path(path)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 中的值覆盖 base，未提供的键保留 base 默认。"""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(path: str | Path = "config/settings.yaml") -> dict:
    """加载全局设置。

    文件不存在或字段缺失时以 SPEC 默认值兜底，返回完整 settings dict。
    """
    p = _resolve(path)
    data: dict = {}
    if p.exists():
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        data = {}
    return _deep_merge(_DEFAULT_SETTINGS, data)


def load_cities(path: str | Path = "config/cities.yaml") -> list[dict]:
    """加载城市列表，返回 list[dict]，schema 见 SPEC 第 3 节。"""
    p = _resolve(path)
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    if not isinstance(data, list):
        raise ValueError(f"cities 配置应为列表: {p}")
    # 补齐可选字段默认值，保证下游模块取键安全
    cities: list[dict] = []
    for item in data:
        cfg = dict(item)
        cfg.setdefault("official_site", None)
        cfg.setdefault("notice_list_url", None)
        cfg.setdefault("list_selector", "a")
        cfg.setdefault("search_aliases", [cfg.get("city", "")])
        cities.append(cfg)
    return cities
