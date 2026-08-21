"""updater：把人工确认后的补丁写回主库。

- apply_patch：按 {"city","changes":{field_path: new_value}} 更新城市记录，
  追加 sources、刷新 last_updated、version 次版本号 +1
- save_db：先快照，再原子写（tmp + rename），最后追加 change_log.json
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from .differ import diff_db, load_db, snapshot


def _bump_minor(version: str) -> str:
    """版本号次版本 +1：'1.0.0' -> '1.1.0'。解析失败时回退为原样+'.1'。"""
    try:
        parts = [int(p) for p in str(version).split(".")]
    except (TypeError, ValueError):
        return f"{version}.1"
    if len(parts) == 1:
        parts.append(0)
    parts[1] += 1
    # 次版本进位后修订号清零（1.0.5 -> 1.1.0）
    parts = parts[:2] + [0] * max(0, len(parts) - 2)
    return ".".join(str(p) for p in parts)


def _set_field_path(record: dict, field_path: str, value) -> None:
    """按 'loan.max_family' 形式写入嵌套字段，中间缺失的层级自动建 dict。"""
    keys = str(field_path).split(".")
    node = record
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[keys[-1]] = value


def _append_source(record: dict, field_path: str, source_url: str, today: str) -> None:
    """把来源 URL 追加到对应顶层小节（deposit/withdrawal/loan）的 sources 列表。

    field_path 第一段不是三类小节时（如 last_updated），追加到城市级 note_sources 不创建，
    直接跳过——sources 仅维护政策字段出处。
    """
    section = str(field_path).split(".", 1)[0]
    if not source_url or section not in ("deposit", "withdrawal", "loan"):
        return
    sec = record.get(section)
    if not isinstance(sec, dict):
        return
    sources = sec.setdefault("sources", [])
    # 同 URL 去重
    if any(isinstance(s, dict) and s.get("url") == source_url for s in sources):
        return
    sources.append({"title": "政策变更来源", "url": source_url, "date": today})


def apply_patch(db: dict, patch: dict, source_url: str) -> dict:
    """应用补丁并返回更新后的 db（就地修改并返回同一对象）。

    patch 格式：{"city": "深圳", "changes": {"loan.max_family": 2400000, ...}}
    """
    city = patch.get("city")
    changes = patch.get("changes") or {}
    today = datetime.now().strftime("%Y-%m-%d")

    record = None
    for item in db.get("cities", []):
        if isinstance(item, dict) and item.get("city") == city:
            record = item
            break
    if record is None:
        raise ValueError(f"数据库中未找到城市：{city!r}")

    for field_path, new_value in changes.items():
        _set_field_path(record, field_path, new_value)
        _append_source(record, field_path, source_url, today)

    record["last_updated"] = today
    db["version"] = _bump_minor(db.get("version", "1.0.0"))
    return db


def save_db(db, settings) -> None:
    """保存主库：先快照当前文件，再原子写（tmp+rename），最后追加 change_log.json。

    settings 需包含 paths.db / paths.snapshots / paths.change_log。
    """
    paths = settings.get("paths", {})
    db_path = paths.get("db", "data/gjj_policy_database.json")
    snapshots_dir = paths.get("snapshots", "data/snapshots")
    change_log_path = paths.get("change_log", "data/change_log.json")

    # 1) 快照旧版本（文件存在才快照，首次写入跳过）
    snapshot_path = None
    if os.path.exists(db_path):
        snapshot_path = snapshot(db_path, snapshots_dir)

    # 2) 原子写：先写同目录 tmp 再 rename，避免中途崩溃留下半个文件
    directory = os.path.dirname(db_path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = db_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, db_path)

    # 3) 追加 change_log.json（JSON 数组，逐条记录）
    # 通过 diff 快照与新库得出本次实际变更，便于审计
    changes = []
    if snapshot_path:
        try:
            events = diff_db(load_db(snapshot_path), db)
            changes = [
                {
                    "city": e.city,
                    "field_path": e.field_path,
                    "old_value": e.old_value,
                    "new_value": e.new_value,
                }
                for e in events
            ]
        except Exception:
            changes = []  # 审计信息缺失不影响写库主流程
    entry = {
        "applied_at": datetime.now().isoformat(timespec="seconds"),
        "version": db.get("version"),
        "snapshot": snapshot_path,
        "changes": changes,
    }
    log = []
    if os.path.exists(change_log_path):
        try:
            with open(change_log_path, "r", encoding="utf-8") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except (json.JSONDecodeError, OSError):
            log = []
    log.append(entry)
    with open(change_log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
        f.write("\n")
