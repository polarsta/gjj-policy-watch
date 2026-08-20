"""differ 离线测试：构造 old/new db 验证 ChangeEvent 输出与 snapshot 文件生成。

不依赖外网；ChangeEvent 结构依赖 gjjwatch.models（SPEC 数据模型契约）。
"""

import json
import os
import re

import pytest

from gjjwatch.differ import diff_db, load_db, snapshot


def _make_db(loan_rate="2.6%", base_upper=35811, cities_order=("北京", "深圳")):
    """构造一个迷你数据库（字段结构仿照种子库）。"""
    city_records = {
        "北京": {
            "city": "北京",
            "province": "北京市",
            "last_updated": "2026-08-20",
            "deposit": {"base_upper": base_upper, "ratio": "5%-12%"},
            "loan": {"rate_first": loan_rate, "max_family": "240万"},
        },
        "深圳": {
            "city": "深圳",
            "province": "广东省",
            "last_updated": "2026-08-20",
            "deposit": {"base_upper": 44955, "ratio": "5%-12%"},
            "loan": {"rate_first": "2.6%", "max_family": "231万"},
        },
    }
    return {
        "database": "测试库",
        "version": "1.0.0",
        "cities": [city_records[c] for c in cities_order],
    }


def test_diff_no_change():
    """完全相同的库（即使城市顺序/缩进不同）不产生任何 ChangeEvent。"""
    old = _make_db()
    new = _make_db(cities_order=("深圳", "北京"))  # 顺序颠倒
    new_json = json.loads(json.dumps(new, indent=8))  # 模拟缩进差异
    assert diff_db(old, new_json) == []


def test_diff_scalar_change():
    """标量字段变更：old/new 值正确记录，field_path 用点号连接。"""
    old = _make_db(loan_rate="2.6%")
    new = _make_db(loan_rate="2.4%")
    events = diff_db(old, new)
    assert len(events) == 1
    e = events[0]
    assert e.city == "北京"
    assert e.field_path == "loan.rate_first"
    assert e.old_value == "2.6%"
    assert e.new_value == "2.4%"
    assert e.detected_at  # ISO 时间戳非空


def test_diff_ignores_top_level_metadata():
    """顶层 version / generated_at 等元信息变更不参与比较。"""
    old = _make_db()
    new = _make_db()
    new["version"] = "9.9.9"
    new["generated_at"] = "2099-01-01"
    assert diff_db(old, new) == []


def test_diff_added_and_removed_field():
    """新增字段与删除字段分别产生 old_value=None / new_value=None 的事件。"""
    old = _make_db()
    new = _make_db()
    new["cities"][0]["loan"]["down_payment_first"] = "20%"   # 新增字段
    del new["cities"][0]["deposit"]["ratio"]                 # 删除字段
    events = {(e.field_path): e for e in diff_db(old, new)}

    added = events["loan.down_payment_first"]
    assert added.old_value is None and added.new_value == "20%"

    removed = events["deposit.ratio"]
    assert removed.old_value == "5%-12%" and removed.new_value is None


def test_diff_new_city():
    """新增城市：该城全部字段按新增（old_value=None）输出，且按 city 对齐不串行。"""
    old = _make_db(cities_order=("北京",))
    new = _make_db()
    events = diff_db(old, new)
    assert events, "新增城市应产生事件"
    assert {e.city for e in events} == {"深圳"}
    assert all(e.old_value is None for e in events)


def test_diff_multiple_cities_aligned_by_city():
    """两城各改一个字段：事件与正确城市关联，互不混淆。"""
    old = _make_db()
    new = _make_db()
    new["cities"][0]["deposit"]["base_upper"] = 36000   # 北京
    new["cities"][1]["loan"]["max_family"] = "240万"    # 深圳
    events = diff_db(old, new)
    by_city = {}
    for e in events:
        by_city.setdefault(e.city, []).append(e)
    assert set(by_city) == {"北京", "深圳"}
    assert [e.field_path for e in by_city["北京"]] == ["deposit.base_upper"]
    assert by_city["北京"][0].old_value == 35811
    assert by_city["北京"][0].new_value == 36000
    assert [e.field_path for e in by_city["深圳"]] == ["loan.max_family"]


def test_load_db_roundtrip(tmp_path):
    """load_db 能读回写入的 JSON。"""
    db = _make_db()
    p = tmp_path / "db.json"
    p.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
    assert load_db(str(p)) == db


def test_snapshot_creates_timestamped_copy(tmp_path):
    """snapshot 生成 snapshots/YYYYMMDD_HHMMSS.json 且内容与原文件一致。"""
    db = _make_db()
    db_path = tmp_path / "db.json"
    db_path.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
    snaps = tmp_path / "snapshots"

    dest = snapshot(str(db_path), str(snaps))

    assert os.path.dirname(dest) == str(snaps)
    assert re.fullmatch(r"\d{8}_\d{6}(_\d+)?\.json", os.path.basename(dest))
    assert json.loads(open(dest, encoding="utf-8").read()) == db
    # 原文件保持不变
    assert json.loads(db_path.read_text(encoding="utf-8")) == db


def test_snapshot_same_second_no_overwrite(tmp_path):
    """同一秒内连续两次快照不互相覆盖。"""
    db_path = tmp_path / "db.json"
    db_path.write_text("{}", encoding="utf-8")
    snaps = tmp_path / "snapshots"
    d1 = snapshot(str(db_path), str(snaps))
    d2 = snapshot(str(db_path), str(snaps))
    assert d1 != d2
    assert os.path.exists(d1) and os.path.exists(d2)
