"""searcher 模块离线测试：bing HTML 解析、build_queries 组合、日期过滤、降级链。

全部离线运行，不依赖外网与真实 API KEY。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from gjjwatch import searcher

FIXTURE = Path(__file__).parent / "fixtures" / "bing_sample.html"


def make_settings(**overrides) -> dict:
    """构造最小可用 settings（等价于 config/settings.yaml 的相关字段）。"""
    settings = {
        "date_window_days": 7,
        "request_timeout": 15,
        "request_delay": 0,  # 测试中不做真实限速
        "user_agent": "test-agent",
        "search": {
            "backend": "bing_html",
            "results_per_query": 10,
            "policy_terms": ["贷款", "提取"],
            "domain_boost": ["gov.cn"],
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(settings.get(key), dict):
            settings[key].update(value)
        else:
            settings[key] = value
    return settings


# ---------------------------------------------------------------------------
# build_queries
# ---------------------------------------------------------------------------

class TestBuildQueries:
    def test_single_alias(self):
        city_cfg = {"city": "深圳", "search_aliases": ["深圳"]}
        queries = searcher.build_queries(city_cfg, make_settings())
        assert queries == ["深圳 公积金 贷款", "深圳 公积金 提取"]

    def test_multiple_aliases(self):
        city_cfg = {"city": "红河", "search_aliases": ["红河州", "红河"]}
        queries = searcher.build_queries(city_cfg, make_settings())
        assert queries == [
            "红河州 公积金 贷款", "红河州 公积金 提取",
            "红河 公积金 贷款", "红河 公积金 提取",
        ]

    def test_alias_fallback_to_city(self):
        city_cfg = {"city": "深圳"}  # 无 search_aliases 字段
        queries = searcher.build_queries(city_cfg, make_settings())
        assert queries == ["深圳 公积金 贷款", "深圳 公积金 提取"]

    def test_default_terms_when_missing(self):
        city_cfg = {"city": "深圳", "search_aliases": ["深圳"]}
        settings = make_settings()
        settings["search"] = {}  # 无 policy_terms
        queries = searcher.build_queries(city_cfg, settings)
        assert len(queries) == len(searcher.DEFAULT_POLICY_TERMS)
        assert all(q.startswith("深圳 公积金 ") for q in queries)


# ---------------------------------------------------------------------------
# 日期提示解析
# ---------------------------------------------------------------------------

class TestParseDateHint:
    def test_absolute_cn(self):
        assert searcher._parse_date_hint("2026年8月20日 发布") == "2026-08-20"

    def test_absolute_iso(self):
        assert searcher._parse_date_hint("2026-08-20") == "2026-08-20"

    def test_absolute_dot(self):
        assert searcher._parse_date_hint("2026.8.5") == "2026-08-05"

    def test_relative_days(self):
        today = date(2026, 8, 20)
        assert searcher._parse_date_hint("3天前", today) == "2026-08-17"

    def test_relative_words(self):
        today = date(2026, 8, 20)
        assert searcher._parse_date_hint("昨天发布", today) == "2026-08-19"
        assert searcher._parse_date_hint("前天", today) == "2026-08-18"
        assert searcher._parse_date_hint("2周前", today) == "2026-08-06"
        assert searcher._parse_date_hint("1个月前", today) == "2026-07-21"

    def test_no_date(self):
        assert searcher._parse_date_hint("没有任何日期的文本") is None
        assert searcher._parse_date_hint("") is None


# ---------------------------------------------------------------------------
# Bing HTML 解析（离线 fixture）
# ---------------------------------------------------------------------------

class TestParseBingHtml:
    def test_parse_fixture(self):
        html = FIXTURE.read_text(encoding="utf-8")
        results = searcher.parse_bing_html(html, make_settings())

        # fixture 中 4 条 b_algo（广告条 b_ad 不应被解析）
        assert len(results) == 4
        assert all(r["engine"] == "bing_html" for r in results)
        assert all({"title", "url", "snippet", "date", "engine"} <= set(r)
                   for r in results)

        # 第 1 条：相对日期 "3天前"
        assert results[0]["title"] == "深圳市住房公积金管理中心关于调整贷款最高额度的通知"
        assert results[0]["url"].startswith("https://zjj.sz.gov.cn/")
        expected = (date.today() - timedelta(days=3)).isoformat()
        assert results[0]["date"] == expected

        # 第 2 条：绝对中文日期
        assert results[1]["date"] == "2026-08-20"

        # 第 3 条：无日期
        assert results[2]["date"] is None

        # 第 4 条：相对日期 "30天前"
        expected_old = (date.today() - timedelta(days=30)).isoformat()
        assert results[3]["date"] == expected_old

    def test_results_per_query_limit(self):
        html = FIXTURE.read_text(encoding="utf-8")
        settings = make_settings(search={"results_per_query": 2})
        results = searcher.parse_bing_html(html, settings)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# search() 降级链
# ---------------------------------------------------------------------------

class TestSearchFallback:
    def test_keyed_backend_missing_key_falls_back(self, monkeypatch):
        """serpapi KEY 缺失时应回退 bing_html。"""
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        called = {}

        def fake_bing(query, settings):
            called["bing"] = True
            return [{"title": "t", "url": "u", "snippet": "s",
                     "date": None, "engine": "bing_html"}]

        monkeypatch.setattr(searcher, "_search_bing_html", fake_bing)
        settings = make_settings(search={"backend": "serpapi"})
        results = searcher.search("深圳 公积金 贷款", settings)
        assert called.get("bing") is True
        assert results and results[0]["engine"] == "bing_html"

    def test_keyed_backend_error_falls_back(self, monkeypatch):
        """有 KEY 的后端抛异常时回退 bing_html。"""
        monkeypatch.setenv("SERPAPI_KEY", "dummy")

        def boom(query, settings):
            raise RuntimeError("network down")

        monkeypatch.setattr(searcher, "_search_serpapi", boom)
        monkeypatch.setattr(
            searcher, "_search_bing_html",
            lambda q, s: [{"title": "t", "url": "u", "snippet": "s",
                           "date": None, "engine": "bing_html"}])
        settings = make_settings(search={"backend": "serpapi"})
        results = searcher.search("q", settings)
        assert len(results) == 1

    def test_all_backends_fail_returns_empty(self, monkeypatch):
        """全部失败返回空列表而不抛异常。"""
        def boom(query, settings):
            raise RuntimeError("network down")

        monkeypatch.setattr(searcher, "_search_bing_html", boom)
        results = searcher.search("q", make_settings())
        assert results == []

    def test_keyed_backend_success_no_fallback(self, monkeypatch):
        monkeypatch.setenv("SERPAPI_KEY", "dummy")
        monkeypatch.setattr(
            searcher, "_search_serpapi",
            lambda q, s: [{"title": "t", "url": "u", "snippet": "s",
                           "date": None, "engine": "serpapi"}])

        def should_not_call(q, s):  # pragma: no cover
            raise AssertionError("不应回退 bing_html")

        monkeypatch.setattr(searcher, "_search_bing_html", should_not_call)
        settings = make_settings(search={"backend": "serpapi"})
        results = searcher.search("q", settings)
        assert results[0]["engine"] == "serpapi"


# ---------------------------------------------------------------------------
# search_city：日期过滤 / 无日期标注 / 域名加权 / 去重
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_search(monkeypatch):
    """替换 searcher.search，返回预置结果集。"""
    def _install(results_by_query: dict[str, list[dict]]):
        def fake(query, settings):
            return results_by_query.get(query, [])
        monkeypatch.setattr(searcher, "search", fake)
    return _install


class TestSearchCity:
    def test_date_filter_and_unknown_date_mark(self, fake_search):
        today = date.today()
        recent = (today - timedelta(days=2)).isoformat()
        old = (today - timedelta(days=30)).isoformat()
        fake_search({
            "深圳 公积金 贷款": [
                {"title": "新政", "url": "https://a.example.com/1",
                 "snippet": "近期发布", "date": recent, "engine": "bing_html"},
                {"title": "旧闻", "url": "https://a.example.com/2",
                 "snippet": "很久以前", "date": old, "engine": "bing_html"},
                {"title": "无日期", "url": "https://a.example.com/3",
                 "snippet": "没有日期", "date": None, "engine": "bing_html"},
            ],
        })
        city_cfg = {"city": "深圳", "search_aliases": ["深圳"]}
        settings = make_settings()  # window=7, policy_terms=[贷款, 提取]
        anns = searcher.search_city(city_cfg, settings)

        titles = [a.title for a in anns]
        assert "新政" in titles
        assert "旧闻" not in titles  # 超出 7 天窗口被过滤
        unknown = next(a for a in anns if a.title == "无日期")
        assert unknown.snippet.startswith("[日期未知]")
        assert unknown.date is None
        assert all(a.channel == "search" for a in anns)
        assert all(a.city == "深圳" for a in anns)
        assert all(len(a.fingerprint) == 32 for a in anns)

    def test_future_date_filtered(self, fake_search):
        future = (date.today() + timedelta(days=3)).isoformat()
        fake_search({
            "深圳 公积金 贷款": [
                {"title": "未来", "url": "https://a.example.com/f",
                 "snippet": "", "date": future, "engine": "bing_html"},
            ],
        })
        anns = searcher.search_city(
            {"city": "深圳", "search_aliases": ["深圳"]}, make_settings())
        assert anns == []

    def test_domain_boost_ordering(self, fake_search):
        recent = date.today().isoformat()
        fake_search({
            "深圳 公积金 贷款": [
                {"title": "商业媒体", "url": "https://news.example.com/a",
                 "snippet": "", "date": recent, "engine": "bing_html"},
                {"title": "官网公告", "url": "https://zjj.sz.gov.cn/b",
                 "snippet": "", "date": recent, "engine": "bing_html"},
            ],
        })
        anns = searcher.search_city(
            {"city": "深圳", "search_aliases": ["深圳"]}, make_settings())
        assert anns[0].title == "官网公告"  # gov.cn 域名排前
        assert anns[1].title == "商业媒体"

    def test_dedup_across_queries(self, fake_search):
        recent = date.today().isoformat()
        dup = {"title": "同一条", "url": "https://a.example.com/dup",
               "snippet": "", "date": recent, "engine": "bing_html"}
        fake_search({
            "深圳 公积金 贷款": [dict(dup)],
            "深圳 公积金 提取": [dict(dup)],
        })
        anns = searcher.search_city(
            {"city": "深圳", "search_aliases": ["深圳"]}, make_settings())
        assert len(anns) == 1


# ---------------------------------------------------------------------------
# search_all：seen 去重
# ---------------------------------------------------------------------------

class TestSearchAll:
    def test_seen_dedup_and_update(self, monkeypatch):
        recent = date.today().isoformat()

        def fake_search_city(city_cfg, settings):
            return [
                searcher.Announcement(
                    city=city_cfg["city"], title=f"{city_cfg['city']}公告",
                    url=f"https://x.example.com/{city_cfg['city']}",
                    date=recent, channel="search",
                    snippet="", fingerprint=f"fp-{city_cfg['city']}"),
            ]

        monkeypatch.setattr(searcher, "search_city", fake_search_city)
        cities = [{"city": "深圳", "search_aliases": ["深圳"]},
                  {"city": "广州", "search_aliases": ["广州"]}]
        seen = {"fp-深圳": "2026-01-01T00:00:00"}  # 深圳已见过
        new, seen = searcher.search_all(cities, make_settings(), seen)

        assert [a.city for a in new] == ["广州"]
        assert "fp-深圳" in seen and "fp-广州" in seen

    def test_city_failure_does_not_crash(self, monkeypatch):
        def boom(city_cfg, settings):
            raise RuntimeError("单城失败")

        monkeypatch.setattr(searcher, "search_city", boom)
        new, seen = searcher.search_all(
            [{"city": "深圳", "search_aliases": ["深圳"]}], make_settings(), {})
        assert new == []
        assert seen == {}
