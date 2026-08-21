"""watcher 模块离线测试：列表提取、相对URL转绝对、seen 去重、失败隔离。

所有测试均通过 monkeypatch 替换 fetch，不访问外网。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gjjwatch import watcher
from gjjwatch.fetcher import FetchError

FIXTURES = Path(__file__).parent / "fixtures"

# 模拟列表页地址（仅用于 urljoin 基准，不会真实请求）
LIST_URL = "https://gjj.example.gov.cn/zwgk/tzgg/index.html"

CITY_CFG = {
    "city": "深圳",
    "province": "广东",
    "official_site": "https://gjj.example.gov.cn",
    "notice_list_url": LIST_URL,
    "list_selector": "div.news-list a",
    "search_aliases": ["深圳"],
}

SETTINGS = {"request_delay": 0, "request_timeout": 5, "user_agent": "test"}


@pytest.fixture
def fake_html() -> str:
    return (FIXTURES / "notice_list_shenzhen.html").read_text(encoding="utf-8")


@pytest.fixture
def patch_fetch(monkeypatch, fake_html):
    """将 watcher.fetch 替换为返回离线 fixture 的假实现。"""
    monkeypatch.setattr(watcher, "fetch", lambda url, settings: fake_html)


class TestScanCity:
    def test_extract_items(self, patch_fetch):
        anns = watcher.scan_city(CITY_CFG, SETTINGS)
        # fixture 中 5 个 <a>：1 个 javascript:、1 个无标题，有效公告 3 条
        assert len(anns) == 3
        assert all(a.channel == "watcher" for a in anns)
        assert all(a.city == "深圳" for a in anns)

    def test_relative_url_to_absolute(self, patch_fetch):
        anns = watcher.scan_city(CITY_CFG, SETTINGS)
        urls = {a.url for a in anns}
        # 根相对路径
        assert "https://gjj.example.gov.cn/zwgk/tzgg/202608/t20260820_1234.html" in urls
        # ../ 相对路径
        assert "https://gjj.example.gov.cn/zwgk/tzgg/t20260715_1200.html" in urls
        # 已是绝对路径的保持不变
        assert "https://gjj.example.gov.cn/detail/1199.html" in urls
        assert all(u.startswith("http") for u in urls)

    def test_title_and_date(self, patch_fetch):
        anns = watcher.scan_city(CITY_CFG, SETTINGS)
        by_title = {a.title: a for a in anns}
        a1 = by_title["关于调整2026年度住房公积金缴存基数的通知"]
        assert a1.date == "2026-08-20"          # 2026-08-20 原样解析
        a2 = by_title["关于开展住房公积金提取业务优化工作的通告"]
        assert a2.date == "2026-07-15"          # 中文日期 2026年7月15日
        a3 = by_title["关于进一步规范公积金贷款额度管理的通知"]
        assert a3.date == "2026-06-03"          # 点号日期 2026.6.3

    def test_fingerprint_stable(self, patch_fetch):
        a = watcher.scan_city(CITY_CFG, SETTINGS)[0]
        b = watcher.scan_city(CITY_CFG, SETTINGS)[0]
        assert a.fingerprint == b.fingerprint

    def test_null_list_url_skipped(self):
        cfg = dict(CITY_CFG, notice_list_url=None)
        assert watcher.scan_city(cfg, SETTINGS) == []


class TestScanAll:
    def test_dedup_with_seen(self, patch_fetch):
        cities = [CITY_CFG]
        fresh, seen = watcher.scan_all(cities, SETTINGS, {})
        assert len(fresh) == 3
        assert len(seen) == 3
        # 第二轮用更新后的 seen 去重，应无新公告
        fresh2, seen2 = watcher.scan_all(cities, SETTINGS, seen)
        assert fresh2 == []
        assert seen2 == seen

    def test_seen_input_not_mutated(self, patch_fetch):
        old_seen: dict = {}
        _, new_seen = watcher.scan_all([CITY_CFG], SETTINGS, old_seen)
        assert old_seen == {}          # 原 dict 不被修改
        assert len(new_seen) == 3

    def test_null_url_city_skipped(self, patch_fetch):
        null_city = dict(CITY_CFG, city="北京", notice_list_url=None)
        fresh, seen = watcher.scan_all([null_city, CITY_CFG], SETTINGS, {})
        assert len(fresh) == 3
        assert all(a.city == "深圳" for a in fresh)

    def test_single_city_failure_not_interrupt(self, monkeypatch, fake_html):
        """单城抓取失败不中断整体流程。"""
        def fake_fetch(url, settings):
            if "bad" in url:
                raise FetchError("模拟网络故障")
            return fake_html

        monkeypatch.setattr(watcher, "fetch", fake_fetch)
        bad_city = dict(CITY_CFG, city="故障城",
                        notice_list_url="https://bad.example.gov.cn/list.html")
        fresh, seen = watcher.scan_all([bad_city, CITY_CFG], SETTINGS, {})
        # 故障城无结果，深圳正常返回
        assert len(fresh) == 3
        assert all(a.city == "深圳" for a in fresh)

    def test_unexpected_parse_error_isolated(self, monkeypatch):
        def boom(url, settings):
            raise RuntimeError("非预期异常")

        monkeypatch.setattr(watcher, "fetch", boom)
        fresh, seen = watcher.scan_all([CITY_CFG], SETTINGS, {})
        assert fresh == []
        assert seen == {}
