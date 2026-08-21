"""Watcher 通道：定向巡检各市公积金中心官网「通知公告」列表页。

接口契约见 SPEC.md 第 5 节：
- scan_city(city_cfg, settings) -> list[Announcement]
- scan_all(cities, settings, seen) -> tuple[list[Announcement], dict]
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .detector import extract_date
from .fetcher import FetchError, fetch
from .models import Announcement


def _extract_anchor(anchor: Tag, base_url: str, city: str) -> Announcement | None:
    """从单个 <a> 标签提取公告；信息不足时返回 None。"""
    # 标题优先取 title 属性（很多列表页链接文本被截断），否则取可见文本
    title = (anchor.get("title") or anchor.get_text(strip=True) or "").strip()
    href = (anchor.get("href") or "").strip()
    if not title or not href:
        return None
    # 过滤无效/脚本链接
    if href.startswith(("javascript:", "#", "mailto:")):
        return None
    abs_url = urljoin(base_url, href)  # 相对 URL 转绝对
    # 日期：从链接文本及其父节点文本中解析（列表页常见 "标题 ... 2026-08-20" 布局）
    context = f"{anchor.get_text(' ', strip=True)} {anchor.parent.get_text(' ', strip=True) if anchor.parent else ''}"
    date = extract_date(context)
    return Announcement(city=city, title=title, url=abs_url, date=date, channel="watcher")


def scan_city(city_cfg: dict, settings: dict) -> list[Announcement]:
    """抓取单城通知公告列表页，返回解析出的公告列表（channel="watcher"）。

    notice_list_url 为空时直接返回空列表；抓取失败抛 FetchError 由上层处理。
    """
    list_url = city_cfg.get("notice_list_url")
    if not list_url:
        return []  # SPEC：notice_list_url 为 null 时跳过该城
    html = fetch(list_url, settings)
    soup = BeautifulSoup(html, "lxml")
    selector = city_cfg.get("list_selector") or "a"
    city = city_cfg.get("city", "")

    announcements: list[Announcement] = []
    seen_fp: set[str] = set()  # 页内去重（同一链接可能被选择器匹配多次）
    for anchor in soup.select(selector):
        if not isinstance(anchor, Tag):
            continue
        ann = _extract_anchor(anchor, list_url, city)
        if ann is None or ann.fingerprint in seen_fp:
            continue
        seen_fp.add(ann.fingerprint)
        announcements.append(ann)
    return announcements


def scan_all(
    cities: list[dict],
    settings: dict,
    seen: dict,
) -> tuple[list[Announcement], dict]:
    """巡检全部城市，返回 (新公告列表, 更新后的 seen)。

    - 按 fingerprint 在 seen 中去重，只返回"新发现"的公告
    - notice_list_url 为 null 的城市跳过
    - 单城抓取/解析失败不中断整体流程（错误记录在 Announcement 之外，
      通过返回值结构无法携带，故打印告警；调用方可用 try/except 细控）
    """
    new_seen = dict(seen)  # 不修改调用方传入的原 dict
    fresh: list[Announcement] = []
    for city_cfg in cities:
        if not city_cfg.get("notice_list_url"):
            continue  # 跳过未配置列表页的城市
        try:
            announcements = scan_city(city_cfg, settings)
        except FetchError as exc:
            # 单城失败仅告警，不中断其他城市
            print(f"[watcher] 城市 {city_cfg.get('city')} 巡检失败: {exc}")
            continue
        except Exception as exc:  # 解析异常同样隔离
            print(f"[watcher] 城市 {city_cfg.get('city')} 解析异常: {exc}")
            continue
        for ann in announcements:
            if ann.fingerprint in new_seen:
                continue  # 已见过，去重
            new_seen[ann.fingerprint] = {
                "city": ann.city,
                "title": ann.title,
                "url": ann.url,
                "date": ann.date,
                "channel": ann.channel,
            }
            fresh.append(ann)
    return fresh, new_seen
