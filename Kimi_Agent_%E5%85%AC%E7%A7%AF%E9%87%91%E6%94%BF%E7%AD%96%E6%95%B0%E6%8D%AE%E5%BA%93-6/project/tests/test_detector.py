"""detector 模块离线测试：关键词命中、分类、中文日期解析。"""

from __future__ import annotations

import pytest

from gjjwatch.detector import classify, extract_date, is_hit
from gjjwatch.models import Announcement

SETTINGS = {
    "keywords": [
        "缴存基数", "贷款额度", "最高额度", "提取", "利率",
        "首付", "调整", "优化", "新政", "通知",
    ]
}


def make_ann(title: str, snippet: str = "") -> Announcement:
    return Announcement(city="深圳", title=title, url="https://x/1", date=None,
                        channel="watcher", snippet=snippet)


class TestIsHit:
    def test_hit_in_title(self):
        assert is_hit(make_ann("关于调整2026年度住房公积金缴存基数的通知"), SETTINGS)

    def test_hit_in_snippet(self):
        ann = make_ann("业务办理指南", snippet="本次优化涉及提取流程")
        assert is_hit(ann, SETTINGS)

    def test_no_hit(self):
        assert not is_hit(make_ann("中心开展消防演练活动"), SETTINGS)

    def test_empty_keywords(self):
        assert not is_hit(make_ann("提取新政"), {"keywords": []})


class TestClassify:
    @pytest.mark.parametrize("title,expected", [
        ("关于调整住房公积金缴存基数的通知", ["deposit"]),
        ("关于优化租房提取公积金的通知", ["withdrawal"]),
        ("关于提高住房公积金贷款最高额度的通知", ["loan"]),
        ("二套房首付比例调整公告", ["loan"]),
        ("关于下调个人住房公积金贷款利率的通知", ["loan", "rate"]),  # 含"贷款"+"利率"
        ("缴存与提取政策同步调整", ["deposit", "withdrawal"]),
        ("贷款额度与利率同步调整", ["loan", "rate"]),
        ("中心举办文明单位创建活动", ["general"]),  # 无映射词 → general
    ])
    def test_classify_mapping(self, title, expected):
        assert classify(make_ann(title)) == expected

    def test_classify_uses_snippet(self):
        ann = make_ann("最新通知", snippet="涉及贷款利率调整")
        assert "loan" in classify(ann)
        assert "rate" in classify(ann)


class TestExtractDate:
    @pytest.mark.parametrize("text,expected", [
        ("2026年8月20日", "2026-08-20"),
        ("发布于2026年8月20日起施行", "2026-08-20"),  # 缺"日"也可解析
        ("2026-08-20", "2026-08-20"),
        ("2026-8-2", "2026-08-02"),
        ("2026.8.20", "2026-08-20"),
        ("2026/08/20", "2026-08-20"),
        ("标题：关于调整的通知（2026年12月1日）", "2026-12-01"),
    ])
    def test_parse_formats(self, text, expected):
        assert extract_date(text) == expected

    @pytest.mark.parametrize("text", [
        None,
        "",
        "没有任何日期的标题",
        "2026年13月40日",  # 非法月日
    ])
    def test_no_date(self, text):
        assert extract_date(text) is None
