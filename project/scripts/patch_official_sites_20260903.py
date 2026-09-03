# -*- coding: utf-8 -*-
"""
把人工查证的公积金官网网址回写进主库 cities[].official_site（2026-09-03）

数据源：export_official_sites.VERIFIED（人工查证结果，含 curl 核验）
硬约束：主库必须 indent=1 + ensure_ascii=False + utf-8-sig 重写，否则 diff 会炸到十万行

用法：
    python3 project/scripts/patch_official_sites_20260903.py          # dry-run
    python3 project/scripts/patch_official_sites_20260903.py --apply  # 落盘
"""
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "project", "scripts"))
from export_official_sites import VERIFIED  # noqa: E402

DB = os.path.join(BASE, "gjj_policy_database.json")
MIRRORS = [
    os.path.join(BASE, "site", "gjj_policy_database.json"),
]


def main():
    apply = "--apply" in sys.argv

    with open(DB, encoding="utf-8-sig") as f:
        db = json.load(f)

    cities = {c["city"]: c for c in db["cities"]}
    log, skipped = [], []

    for city, (url, origin, note) in VERIFIED.items():
        if city not in cities:
            skipped.append(f"[未匹配] {city} —— 库中无此城市")
            continue
        if not url:
            skipped.append(f"[跳过] {city} —— {note}")
            continue
        old = (cities[city].get("official_site") or "").strip()
        if old == url:
            skipped.append(f"[无变化] {city} —— {url}")
            continue
        if apply:
            cities[city]["official_site"] = url
        log.append(f"{city}\n    旧: {old or '(空)'}\n    新: {url}\n    口径: {origin}\n    备注: {note}")

    print(f"待写入 {len(log)} 条；跳过/无变化 {len(skipped)} 条")
    for s in skipped:
        print("  " + s)
    print()
    for line in log:
        print(line)

    if not apply:
        print("\n[dry-run] 未落盘。加 --apply 执行。")
        return

    if not log:
        print("\n无变更，不写盘。")
        return

    backup = DB + ".bak_pre_officialsite"
    shutil.copy2(DB, backup)
    print(f"\n已备份: {backup}")

    # 关键：indent=1 与原有格式一致
    with open(DB, "w", encoding="utf-8-sig") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    print(f"已写入: {DB}")

    for m in MIRRORS:
        if os.path.exists(m):
            shutil.copy2(DB, m)
            print(f"已同步镜像: {m}")
        else:
            print(f"[警告] 镜像不存在，未同步: {m}")


if __name__ == "__main__":
    main()
