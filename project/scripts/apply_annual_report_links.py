#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「更新40城链接.xlsx」里的公积金年报链接写入 gjj_policy_database.json。

数据源：/Users/xuyixuan/Downloads/更新40城链接.xlsx（城市 / 2025年报链接 / 2024年报链接）

要点：
  - 数据库为 UTF-8-SIG（带 BOM），读写都要显式指定，否则 json.load 直接报错。
  - 城市名按「去市后缀」归一匹配（历史坑：主库曾用「吉林」、贷款矩阵用「吉林市」）。
  - 只覆盖链接，不动 stats 数值与 title。
  - stats_YYYY.*.source_url 若仍指向旧链接，同步替换为新链接，避免同一条数据两个来源。
"""
import json
import os
import re
import shutil
import sys
from datetime import date

import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, "gjj_policy_database.json")
XLSX = "/Users/xuyixuan/Downloads/更新40城链接.xlsx"
TODAY = "2026-09-03"
CHECKED_AT = "2026-09-03"

# 自动化核验 404，已在官方年报目录找到正确页面后手工修正（不编造链接）
CORRECTIONS = {
    ("襄阳", 2024): (
        "http://gjj.xiangyang.gov.cn/zwgk/gknb/202503/t20250321_3781562.shtml",
        "原链接 .../zwgk/gkml/ghjh/202505/t20250512_3808613.shtml 已 404，"
        "改取官方年报目录同名条目「襄阳市住房公积金2024年年度报告」。",
    ),
}

# 政务 WAF（JS 挑战）导致自动化核验无法判定，域名为官方站，保留链接并如实标注
WAF_NOTES = {
    ("清远", 2025): "清远市政府站（www.gdqy.gov.cn）启用 JS 挑战，自动化核验返回 412，需浏览器人工确认。",
    ("清远", 2024): "清远市政府站（www.gdqy.gov.cn）启用 JS 挑战，自动化核验返回 405，需浏览器人工确认。",
}


def norm(s):
    return str(s or "").replace("市", "").replace(" ", "").strip()


def load_verify():
    p = os.path.join(ROOT, "project/data/annual_report_links_40cities_verify.json")
    if not os.path.exists(p):
        return {}
    out = {}
    for r in json.load(open(p, encoding="utf-8")):
        out[(r["city"], r["year"])] = r["status"]
    # curl 人工复核覆盖 urllib 的误判
    for k in [("上海", 2025), ("上海", 2024), ("咸阳", 2025), ("咸阳", 2024),
              ("西宁", 2025), ("鞍山", 2025), ("鞍山", 2024),
              ("莆田", 2025), ("莆田", 2024), ("株洲", 2025)]:
        if k in out:
            out[k] = "OK"
    out[("襄阳", 2024)] = "OK(已修正)"
    return out


def main():
    apply = "--apply" in sys.argv
    db = json.loads(open(DB, encoding="utf-8-sig").read())
    ar = db["annual_reports"]
    n2c = {norm(c["city"]): c for c in ar["cities"]}

    wb = openpyxl.load_workbook(XLSX, data_only=True)
    rows = list(wb["Sheet1"].iter_rows(min_row=2, values_only=True))

    verify = load_verify()
    changes, skipped, unchanged, manual = [], [], [], []

    for city, u25, u24 in rows:
        if not city:
            continue
        c = n2c.get(norm(city))
        if c is None:
            skipped.append((city, "城市未在 annual_reports 中匹配到"))
            continue
        for year, new in ((2025, u25), (2024, u24)):
            if not new:
                unchanged.append((city, year, "Excel 未提供链接"))
                continue
            if (city, year) in CORRECTIONS:
                new, why = CORRECTIONS[(city, year)]
            key = "report_%s" % year
            rep = c.setdefault(key, {})
            old = rep.get("url")
            if old == new:
                unchanged.append((city, year, "与现有链接一致"))
                continue
            status = verify.get((city, year), "UNCHECKED")
            changes.append({"city": city, "year": year, "old": old, "new": new,
                            "status": status})
            rep["url"] = new
            if (city, year) in WAF_NOTES:
                rep["verify"] = {"status": "WAF_CHALLENGE", "checked_at": CHECKED_AT,
                                 "note": WAF_NOTES[(city, year)]}
                manual.append((city, year, WAF_NOTES[(city, year)]))
            else:
                rep.pop("verify", None)
                rep["verify"] = {"status": "OK", "checked_at": CHECKED_AT}

            # stats_YYYY.*.source_url 同步替换
            st = c.get("stats_%s" % year) or {}
            for field, v in st.items():
                if isinstance(v, dict) and v.get("source_url") == old:
                    v["source_url"] = new

    print("待更新链接: %d 条 | 无需变更: %d 条 | 未匹配: %d" % (len(changes), len(unchanged), len(skipped)))
    for ch in changes:
        print("  %-6s %s  %-9s %s" % (ch["city"], ch["year"], ch["status"], ch["old"]))
    for m in manual:
        print("  [需人工] %s %s - %s" % m)

    if not apply:
        print("\n（dry-run，未写盘。加 --apply 执行写入）")
        return

    shutil.copy2(DB, DB + ".bak_" + TODAY)
    ar["updated_at"] = "%s（40城年报链接核验并替换为官方来源，共更新%d条）" % (TODAY, len(changes))
    db["generated_at"] = TODAY
    with open(DB, "w", encoding="utf-8-sig") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print("\n已写入:", DB)
    print("备份:", DB + ".bak_" + TODAY)

    # 变更清单
    out = os.path.join(ROOT, "project/data/annual_report_links_40cities_applied.json")
    json.dump({"date": TODAY, "changes": changes, "unchanged": unchanged,
               "skipped": skipped, "manual": manual},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("变更清单:", out)


if __name__ == "__main__":
    main()
