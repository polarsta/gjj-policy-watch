"""cli：命令行入口 `python -m gjjwatch.cli`。

子命令：
- daily       每日巡检：watcher 官网巡检 + searcher 搜索兜底 → 关键词过滤 → 通知（不动数据库）
- search      手动搜索单城：--city 深圳 [--days 30]
- weekly      周报：daily 全流程 + sources URL 抽样健康检查 → reports/weekly_YYYYMMDD.md
- apply-patch 人工确认后应用补丁：--file patch.json
- init-seen   首次运行初始化：把当前可见公告全部标记为已见，避免首日海量误报
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime

from .config import load_cities, load_settings
from .detector import is_hit
from .differ import load_db
from .fetcher import FetchError, fetch
from .models import ScanResult
from .notifier import notify, render_markdown
from .searcher import search_all, search_city
from .updater import apply_patch, save_db
from .watcher import scan_all

# URL 健康检查抽样数量上限
_HEALTH_SAMPLE_SIZE = 20


def _load_seen(settings: dict) -> dict:
    """读取已见公告指纹表；文件不存在或损坏时返回空 dict。"""
    path = settings.get("paths", {}).get("seen", "data/seen_announcements.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_seen(settings: dict, seen: dict) -> None:
    """原子写已见指纹表。"""
    path = settings.get("paths", {}).get("seen", "data/seen_announcements.json")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def _scan(settings: dict, cities: list, seen: dict) -> ScanResult:
    """执行双通道巡检（watcher + searcher），返回汇总 ScanResult。

    注意：只读/更新内存中的 seen，落盘由调用方决定。
    """
    errors: list[str] = []
    announcements: list = []

    try:
        watcher_new, seen = scan_all(cities, settings, seen)
        announcements.extend(watcher_new)
    except Exception as exc:  # 单通道失败不拖垮整体
        errors.append(f"watcher 通道异常: {exc}")

    try:
        search_new, seen = search_all(cities, settings, seen)
        announcements.extend(search_new)
    except Exception as exc:
        errors.append(f"search 通道异常: {exc}")

    hits = [a for a in announcements if is_hit(a, settings)]
    result = ScanResult(
        run_at=datetime.now().isoformat(timespec="seconds"),
        announcements=announcements,
        hits=hits,
        errors=errors,
    )
    result._seen = seen  # 传递给调用方落盘（非数据模型字段）
    return result


def cmd_daily(args) -> int:
    """每日巡检：发现 → 过滤 → 通知，不修改数据库。"""
    settings = load_settings()
    cities = load_cities()
    seen = _load_seen(settings)
    result = _scan(settings, cities, seen)
    _save_seen(settings, result._seen)
    notify(result, [], settings)
    return 0


def cmd_search(args) -> int:
    """手动搜索单城，--days 覆盖 settings 的 date_window_days。"""
    settings = load_settings()
    cities = load_cities()
    if args.days:
        settings["date_window_days"] = args.days

    target = None
    for cfg in cities:
        names = [cfg.get("city")] + list(cfg.get("search_aliases") or [])
        if args.city in names:
            target = cfg
            break
    if target is None:
        print(f"未在 cities.yaml 中找到城市：{args.city}", file=sys.stderr)
        return 1

    announcements = search_city(target, settings)
    print(f"城市：{target.get('city')}  日期范围：最近 {settings.get('date_window_days')} 天  命中 {len(announcements)} 条")
    for a in announcements:
        flag = "HIT" if is_hit(a, settings) else "   "
        print(f"[{flag}] {a.date or '????-??-??'} {a.title}\n      {a.url}")
    return 0


def _health_check_sources(db: dict, settings: dict, sample_size: int = _HEALTH_SAMPLE_SIZE) -> list[dict]:
    """抽样校验各城市 sources URL 可达性，返回 [{city,url,ok,error}]。"""
    pool = []
    for item in db.get("cities", []):
        city = item.get("city")
        for section in ("deposit", "withdrawal", "loan"):
            for src in (item.get(section) or {}).get("sources") or []:
                url = src.get("url") if isinstance(src, dict) else None
                if url:
                    pool.append({"city": city, "url": url})
    if len(pool) > sample_size:
        pool = random.sample(pool, sample_size)

    checks = []
    for entry in pool:
        ok, error = True, ""
        try:
            fetch(entry["url"], settings)
        except FetchError as exc:
            ok, error = False, str(exc)
        except Exception as exc:  # 防御：健康检查不崩溃主流程
            ok, error = False, f"{type(exc).__name__}: {exc}"
        checks.append({**entry, "ok": ok, "error": error})
    return checks


def cmd_weekly(args) -> int:
    """周报：daily 全流程 + sources URL 抽样健康检查，输出 Markdown 到 reports/。"""
    settings = load_settings()
    cities = load_cities()
    seen = _load_seen(settings)
    result = _scan(settings, cities, seen)
    _save_seen(settings, result._seen)
    notify(result, [], settings)

    db_path = settings.get("paths", {}).get("db", "data/gjj_policy_database.json")
    checks = _health_check_sources(load_db(db_path), settings)
    broken = [c for c in checks if not c["ok"]]

    # 组装周报：巡检结果 + 健康检查
    lines = [render_markdown(result, []), "", "---", "", "## 来源链接健康检查（抽样）", ""]
    lines.append(f"- 抽样 {len(checks)} 条，失效 {len(broken)} 条")
    for c in checks:
        mark = "OK" if c["ok"] else f"FAIL ({c['error']})"
        lines.append(f"- [{mark}] {c['city']} {c['url']}")
    report = "\n".join(lines) + "\n"

    reports_dir = settings.get("paths", {}).get("reports", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, f"weekly_{datetime.now().strftime('%Y%m%d')}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"周报已输出：{report_path}")
    return 0


def cmd_apply_patch(args) -> int:
    """应用人工确认后的补丁文件（{"city","changes":{...}}），快照 + 原子写库 + 变更日志。"""
    settings = load_settings()
    with open(args.file, "r", encoding="utf-8") as f:
        patch = json.load(f)

    db_path = settings.get("paths", {}).get("db", "data/gjj_policy_database.json")
    db = load_db(db_path)
    source_url = patch.get("source_url", "")
    db = apply_patch(db, patch, source_url)
    save_db(db, settings)

    changes = patch.get("changes") or {}
    print(f"已应用补丁：城市={patch.get('city')} 字段数={len(changes)} 新版本={db.get('version')}")
    for field_path, value in changes.items():
        print(f"  {field_path} -> {value}")
    return 0


def cmd_init_seen(args) -> int:
    """首日初始化：扫描当前所有可见公告并全部标记为已见（不通知、不写库）。"""
    settings = load_settings()
    cities = load_cities()
    result = _scan(settings, cities, {})
    _save_seen(settings, result._seen)
    print(
        f"init-seen 完成：已标记 {len(result._seen)} 条公告指纹；"
        f"本次扫描可见公告 {len(result.announcements)} 条，错误 {len(result.errors)} 个。"
    )
    if result.errors:
        for err in result.errors:
            print(f"  [error] {err}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m gjjwatch.cli",
        description="公积金政策监测系统",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_daily = sub.add_parser("daily", help="每日巡检（不动数据库）")
    p_daily.set_defaults(func=cmd_daily)

    p_search = sub.add_parser("search", help="手动搜索单城")
    p_search.add_argument("--city", required=True, help="城市名或别名，如 深圳")
    p_search.add_argument("--days", type=int, default=None, help="日期范围天数，覆盖 settings")
    p_search.set_defaults(func=cmd_search)

    p_weekly = sub.add_parser("weekly", help="周报 + URL 健康检查")
    p_weekly.set_defaults(func=cmd_weekly)

    p_patch = sub.add_parser("apply-patch", help="应用人工确认后的补丁")
    p_patch.add_argument("--file", required=True, help="补丁 JSON 文件路径")
    p_patch.set_defaults(func=cmd_apply_patch)

    p_init = sub.add_parser("init-seen", help="首日初始化已见指纹表")
    p_init.set_defaults(func=cmd_init_seen)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
