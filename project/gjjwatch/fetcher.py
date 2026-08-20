"""HTTP 抓取模块。

fetch() 带 UA、超时、重试 2 次、礼貌限速；失败抛 FetchError。
接口契约见 SPEC.md 第 5 节。
"""

from __future__ import annotations

import time

import requests


class FetchError(Exception):
    """抓取失败（重试耗尽或返回非 2xx）。"""


def fetch(url: str, settings: dict) -> str:
    """抓取 url 并返回文本内容。

    - UA 取 settings["user_agent"]
    - 超时取 settings["request_timeout"]（秒）
    - 最多尝试 3 次（首次 + 重试 2 次）
    - 每次请求前 sleep(settings["request_delay"]) 做礼貌限速
    - 全部失败抛 FetchError
    """
    timeout = float(settings.get("request_timeout", 15))
    delay = float(settings.get("request_delay", 1.0))
    headers = {"User-Agent": settings.get("user_agent", "gjj-policy-watch/1.0")}

    last_error: Exception | None = None
    for attempt in range(3):  # 1 次首发 + 2 次重试
        if delay > 0:
            time.sleep(delay)  # 限速：任何请求前先等待
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            # 处理部分政府网站未声明编码的情况
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException as exc:
            last_error = exc
    raise FetchError(f"抓取失败（已重试2次）: {url} -> {last_error}")
