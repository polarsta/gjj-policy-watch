"""differ：数据库版本对比与快照。

- load_db：加载主库 JSON
- diff_db：按 city 对齐比较 cities 数组内的字段，输出 ChangeEvent 列表
- snapshot：把当前数据库复制为 snapshots/YYYYMMDD_HHMMSS.json
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

from .models import ChangeEvent


def load_db(path) -> dict:
    """加载主库 JSON，返回 dict。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _index_by_city(db: dict) -> dict:
    """把 db["cities"] 数组转成 {city名: 城市记录}，用于对齐比较。"""
    return {c.get("city"): c for c in db.get("cities", []) if isinstance(c, dict)}


def _flatten(obj, prefix: str = "") -> dict:
    """把嵌套 dict 拍平为 {field_path: value}。

    - dict 递归展开，key 用 "." 连接，如 "loan.max_family"
    - list / 标量作为叶子值整体比较，内容不同即视为变更
    """
    flat = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                flat.update(_flatten(value, path))
            else:
                flat[path] = value
    else:
        flat[prefix] = obj
    return flat


def diff_db(old: dict, new: dict) -> list[ChangeEvent]:
    """比较两个数据库版本，仅比较 cities 数组内字段（按 city 对齐）。

    忽略整体缩进/城市顺序；顶层 version/generated_at 等元信息不参与比较。
    新增/删除的字段同样产生 ChangeEvent（另一侧值为 None）。
    """
    old_cities = _index_by_city(old)
    new_cities = _index_by_city(new)
    detected_at = datetime.now().isoformat(timespec="seconds")

    events: list[ChangeEvent] = []
    # 以 new 的城市顺序为主输出，旧库多出而 new 缺失的城市也纳入
    for city in list(new_cities.keys()) + [c for c in old_cities if c not in new_cities]:
        old_flat = _flatten(old_cities.get(city, {}))
        new_flat = _flatten(new_cities.get(city, {}))
        for field_path in sorted(set(old_flat) | set(new_flat)):
            old_value = old_flat.get(field_path)
            new_value = new_flat.get(field_path)
            if old_value != new_value:
                events.append(
                    ChangeEvent(
                        city=city,
                        field_path=field_path,
                        old_value=old_value,
                        new_value=new_value,
                        source_url="",  # 来源 URL 由调用方（updater/报告层）补充
                        detected_at=detected_at,
                    )
                )
    return events


def snapshot(db_path, snapshots_dir) -> str:
    """把 db_path 复制为 snapshots_dir/YYYYMMDD_HHMMSS.json，返回快照路径。"""
    os.makedirs(snapshots_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(snapshots_dir, f"{stamp}.json")
    # 同一秒内重复快照时加序号后缀，避免覆盖
    seq = 1
    while os.path.exists(dest):
        dest = os.path.join(snapshots_dir, f"{stamp}_{seq}.json")
        seq += 1
    shutil.copyfile(db_path, dest)
    return dest
