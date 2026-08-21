"""Searcher 通道：按「城市名 + 公积金 + 政策关键词」搜索并限定日期范围锁定最新政策。

默认后端为 bing_html（无 KEY 依赖，直接抓取 Bing 搜索结果页并解析）；
可选后端 serpapi / tavily / bocha 需要对应环境变量 API KEY。
所有后端失败都会降级回退 bing_html，仍失败仅记录 error 不抛异常。

接口契约（见 SPEC 第 5 节）：
- build_queries(city_cfg, settings) -> list[str]
- search(query, settings) -> list[dict]
- search_city(city_cfg, settings) -> list[Announcement]
- search_all(cities, settings, seen) -> tuple[list[Announcement], dict]
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from gjjwatch.models import Announcement

logger = logging.getLogger(__name__)

# 各后端 API 地址
BING_SEARCH_URL = "https://www.bing.com/search"
SERPAPI_URL = "https://serpapi.com/search.json"
TAVILY_URL = "https://api.tavily.com/search"
BOCHA_URL = "https://api.bochaai.com/v1/web-search"

# 默认搜索政策关键词（settings.search.policy_terms 缺省时使用）
DEFAULT_POLICY_TERMS = ["贷款", "提取", "缴存", "利率", "首付"]


# ---------------------------------------------------------------------------
# 查询词构造
# ---------------------------------------------------------------------------

def build_queries(city_cfg: dict, settings: dict) -> list[str]:
    """对每个 search_alias × policy_terms 组合生成查询词，如 "深圳 公积金 贷款"。"""
    aliases = city_cfg.get("search_aliases") or [city_cfg["city"]]
    terms = settings.get("search", {}).get("policy_terms") or DEFAULT_POLICY_TERMS
    return [f"{alias} 公积金 {term}" for alias in aliases for term in terms]


# ---------------------------------------------------------------------------
# 日期解析小工具（独立实现，不 import detector，避免并行分支合并冲突）
# ---------------------------------------------------------------------------

def _parse_date_hint(text: str, today: date | None = None) -> str | None:
    """从摘要/标题中解析日期，支持中文绝对日期与相对日期，返回 ISO 日期或 None。

    支持格式示例：
      - 2026年8月20日 / 2026-08-20 / 2026.8.20 / 2026/08/20
      - 今天 / 昨天 / 前天 / N天前 / N小时前 / N周前 / N个月前
    """
    if not text:
        return None
    if today is None:
        today = date.today()

    # 绝对日期：2026年8月20日 / 2026-08-20 / 2026.8.20 / 2026/8/20
    m = re.search(r"(20\d{2})\s*[年\-./]\s*(\d{1,2})\s*[月\-./]\s*(\d{1,2})\s*日?", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            pass

    # 相对日期
    if "今天" in text:
        return today.isoformat()
    if "昨天" in text:
        return (today - timedelta(days=1)).isoformat()
    if "前天" in text:
        return (today - timedelta(days=2)).isoformat()
    m = re.search(r"(\d+)\s*小时前", text)
    if m:
        return today.isoformat()  # 当天
    m = re.search(r"(\d+)\s*天前", text)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r"(\d+)\s*(?:周|星期)前", text)
    if m:
        return (today - timedelta(weeks=int(m.group(1)))).isoformat()
    m = re.search(r"(\d+)\s*(?:个)?月前", text)
    if m:
        return (today - timedelta(days=30 * int(m.group(1)))).isoformat()

    # 英文月份缩写（Bing 英文摘要偶发出现），如 "Aug 20, 2026"
    m = re.search(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d{2})",
        text,
    )
    if m:
        months = ["jan", "feb", "mar", "apr", "may", "jun",
                  "jul", "aug", "sep", "oct", "nov", "dec"]
        try:
            month = months.index(m.group(1).lower()[:3]) + 1
            return date(int(m.group(3)), month, int(m.group(2))).isoformat()
        except (ValueError, IndexError):
            pass

    return None


def _in_window(iso_date: str | None, window_days: int, today: date | None = None) -> bool:
    """判断 ISO 日期是否在最近 window_days 天内；无日期视为不在窗口内。"""
    if not iso_date:
        return False
    try:
        d = date.fromisoformat(iso_date[:10])
    except ValueError:
        return False
    if today is None:
        today = date.today()
    return today - timedelta(days=window_days) <= d <= today


# ---------------------------------------------------------------------------
# 后端实现
# ---------------------------------------------------------------------------

def _http_get(url: str, settings: dict, **kwargs) -> requests.Response:
    """带 UA 与超时的 GET 请求。"""
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", settings.get(
        "user_agent", "Mozilla/5.0 (compatible; gjj-policy-watch/1.0)"))
    resp = requests.get(url, headers=headers,
                        timeout=settings.get("request_timeout", 15), **kwargs)
    resp.raise_for_status()
    return resp


def _search_bing_html(query: str, settings: dict) -> list[dict]:
    """默认后端：抓取 Bing 搜索结果页并解析。

    通过 filters=ex1:"ez{N}" 参数让 Bing 只返回最近 N 天的结果（N=date_window_days）。
    """
    window_days = int(settings.get("date_window_days", 7))
    resp = _http_get(
        BING_SEARCH_URL,
        settings,
        params={"q": query, "filters": f'ex1:"ez{window_days}"'},
    )
    return parse_bing_html(resp.text, settings)


def parse_bing_html(html: str, settings: dict) -> list[dict]:
    """解析 Bing 搜索结果页 HTML，提取 li.b_algo 中的 title/url/snippet/date。"""
    max_results = int(settings.get("search", {}).get("results_per_query", 10))
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")
        if a is None:
            continue
        title = a.get_text(strip=True)
        url = a.get("href", "")
        if not url:
            continue
        snippet_node = li.select_one(".b_caption p") or li.select_one("p")
        snippet = snippet_node.get_text(strip=True) if snippet_node else ""
        # 日期优先从摘要文本解析（Bing 常在摘要前缀给出相对/绝对日期）
        date_hint = _parse_date_hint(snippet) or _parse_date_hint(title)
        results.append({
            "title": title,
            "url": url,
            "snippet": snippet,
            "date": date_hint,
            "engine": "bing_html",
        })
        if len(results) >= max_results:
            break
    return results


def _search_serpapi(query: str, settings: dict) -> list[dict] | None:
    """SerpApi 后端；KEY 缺失返回 None（交由上层降级）。"""
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        logger.warning("SERPAPI_KEY 未设置，跳过 serpapi 后端")
        return None
    resp = _http_get(
        SERPAPI_URL,
        settings,
        params={"engine": "bing", "q": query, "api_key": key},
    )
    data = resp.json()
    results = []
    for item in data.get("organic_results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "date": _parse_date_hint(item.get("date") or item.get("snippet") or ""),
            "engine": "serpapi",
        })
    return results


def _search_tavily(query: str, settings: dict) -> list[dict] | None:
    """Tavily 后端；KEY 缺失返回 None。"""
    key = os.environ.get("TAVILY_KEY")
    if not key:
        logger.warning("TAVILY_KEY 未设置，跳过 tavily 后端")
        return None
    window_days = int(settings.get("date_window_days", 7))
    max_results = int(settings.get("search", {}).get("results_per_query", 10))
    resp = requests.post(
        TAVILY_URL,
        json={"api_key": key, "query": query,
              "days": window_days, "max_results": max_results},
        timeout=settings.get("request_timeout", 15),
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
            "date": _parse_date_hint(item.get("published_date") or item.get("content") or ""),
            "engine": "tavily",
        })
    return results


def _search_bocha(query: str, settings: dict) -> list[dict] | None:
    """博查（Bocha）后端；KEY 缺失返回 None。"""
    key = os.environ.get("BOCHA_KEY")
    if not key:
        logger.warning("BOCHA_KEY 未设置，跳过 bocha 后端")
        return None
    window_days = int(settings.get("date_window_days", 7))
    # 博查 freshness 参数仅支持固定档位，取不小于窗口的最小档
    freshness = "oneDay" if window_days <= 1 else (
        "oneWeek" if window_days <= 7 else (
            "oneMonth" if window_days <= 30 else "noLimit"))
    max_results = int(settings.get("search", {}).get("results_per_query", 10))
    resp = requests.post(
        BOCHA_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={"query": query, "freshness": freshness, "count": max_results},
        timeout=settings.get("request_timeout", 15),
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("data", {}).get("webPages", {}).get("value", []):
        results.append({
            "title": item.get("name", ""),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", ""),
            "date": _parse_date_hint(item.get("datePublished") or item.get("snippet") or ""),
            "engine": "bocha",
        })
    return results


# 有 KEY 的后端名称集合；函数在调用时动态解析（便于测试 monkeypatch）
_KEYED_BACKENDS = ("serpapi", "tavily", "bocha")


# ---------------------------------------------------------------------------
# 搜索入口（含降级链）
# ---------------------------------------------------------------------------

def search(query: str, settings: dict) -> list[dict]:
    """按 settings["search"]["backend"] 分发搜索；失败自动降级。

    降级链：配置的有 KEY 后端（KEY 缺失或请求失败）→ bing_html → 仍失败记录
    error 并返回空列表，绝不向外抛异常。
    """
    backend = settings.get("search", {}).get("backend", "bing_html")

    if backend in _KEYED_BACKENDS:
        backend_fn = globals()[f"_search_{backend}"]
        try:
            results = backend_fn(query, settings)
            if results is not None:
                return results
            logger.info("后端 %s 不可用，回退 bing_html", backend)
        except Exception as exc:  # noqa: BLE001 - 降级链要求兜底
            logger.warning("后端 %s 搜索失败（%s），回退 bing_html", backend, exc)
    elif backend != "bing_html":
        logger.warning("未知后端 %r，使用默认 bing_html", backend)

    try:
        return _search_bing_html(query, settings)
    except Exception as exc:  # noqa: BLE001 - 最终兜底，不崩溃
        logger.error("bing_html 搜索失败：query=%r, error=%s", query, exc)
        return []


# ---------------------------------------------------------------------------
# 城市级搜索：日期过滤 / 去重 / 域名加权 / 限速
# ---------------------------------------------------------------------------

def _fingerprint(city: str, title: str, url: str) -> str:
    """md5(city+title+url)，用于跨轮去重。"""
    return hashlib.md5(f"{city}{title}{url}".encode("utf-8")).hexdigest()


def _domain_boost_score(url: str, boost_domains: list[str]) -> int:
    """命中加权域名返回 0（排最前），否则返回 1。"""
    host = urlparse(url).netloc.lower()
    for domain in boost_domains:
        domain = domain.lower().lstrip(".")
        if host == domain or host.endswith("." + domain):
            return 0
    return 1


def search_city(city_cfg: dict, settings: dict) -> list[Announcement]:
    """对单城执行全部查询，做日期过滤、去重与域名加权排序。

    - 仅保留 date 在最近 settings["date_window_days"] 天内的结果；
    - 无日期的结果保留，并在 snippet 前缀标注 "[日期未知]"；
    - 结果按 settings["search"]["domain_boost"] 配置的域名（如 gov.cn）优先排序。
    """
    city = city_cfg["city"]
    window_days = int(settings.get("date_window_days", 7))
    boost_domains = settings.get("search", {}).get("domain_boost") or []
    delay = float(settings.get("request_delay", 1.0))

    today = date.today()
    seen_fp: set[str] = set()
    announcements: list[Announcement] = []

    queries = build_queries(city_cfg, settings)
    for i, query in enumerate(queries):
        if i > 0 and delay > 0:
            time.sleep(delay)  # 礼貌限速
        results = search(query, settings)
        for item in results:
            raw_date = item.get("date")
            iso_date = raw_date[:10] if raw_date else None
            snippet = item.get("snippet", "")
            if iso_date:
                # 有日期：超出窗口直接丢弃
                if not _in_window(iso_date, window_days, today):
                    continue
            else:
                # 无日期：保留但标注
                if not snippet.startswith("[日期未知]"):
                    snippet = "[日期未知]" + snippet

            fp = _fingerprint(city, item.get("title", ""), item.get("url", ""))
            if fp in seen_fp:
                continue
            seen_fp.add(fp)

            announcements.append(Announcement(
                city=city,
                title=item.get("title", ""),
                url=item.get("url", ""),
                date=iso_date,
                channel="search",
                snippet=snippet,
                fingerprint=fp,
            ))

    # 域名加权排序：boost 域名靠前（稳定排序，保持原有相对顺序）
    announcements.sort(key=lambda a: _domain_boost_score(a.url, boost_domains))
    return announcements


def search_all(cities: list[dict], settings: dict,
               seen: dict) -> tuple[list[Announcement], dict]:
    """遍历所有城市执行搜索，与 seen 去重后返回 (新公告列表, 更新后的 seen)。

    seen 结构：{fingerprint: 首次发现的 ISO 时间}。
    """
    new_announcements: list[Announcement] = []
    for city_cfg in cities:
        try:
            city_results = search_city(city_cfg, settings)
        except Exception as exc:  # noqa: BLE001 - 单城失败不影响整体
            logger.error("城市 %s 搜索失败：%s", city_cfg.get("city"), exc)
            continue
        for ann in city_results:
            if ann.fingerprint in seen:
                continue
            seen[ann.fingerprint] = datetime.now().isoformat(timespec="seconds")
            new_announcements.append(ann)
    return new_announcements, seen
