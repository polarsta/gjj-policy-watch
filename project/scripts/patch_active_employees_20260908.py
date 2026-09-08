# -*- coding: utf-8 -*-
"""
2025 年报「实缴职工人数(active_employees)」同比 —— 定点补丁（2026-09-08 用户人工核定）。

大庆：active_employees = 38.78 万人，补 yoy = **-3.94%**
  年报原文未单独披露实缴职工人数同比，该值由用户 2026-09-08 人工核定
  （按 -3.94% 反推 2024 年末实缴职工约 40.37 万人，与黑龙江省年报分市表口径吻合）。

说明：全库 133 城 active_employees 当前均无 yoy 字段（此前只做了 loan_balance），
本补丁仅按要求为大庆补一条，其余城市不动。

版本号 1.5.9 → 1.6.0。写库遵循项目规范：detect_indent 取全文件最小正缩进（主库=1 空格）、
保留原始 EOF 状态、dry-run 默认、--apply 落盘。
"""
import os
import re
import json
import argparse
import difflib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DB = os.path.join(REPO, 'gjj_policy_database.json')

NEW_VERSION = '1.6.0'

DAQING_URL = 'https://www.hlj.gov.cn/hlj/c108459/202605/c00_31941971.shtml'
DAQING_NAME = '大庆市住房公积金2025年数据（市级年报全文未检索到；取自黑龙江省2025年年度报告）'

PATCH = {
    '大庆': {
        'yoy': '-3.94%',
        'source_url': DAQING_URL,
        'source_name': DAQING_NAME,
        'extract_method': '用户人工核定（2026-09-08）',
        'note': '实缴职工人数 38.78 万人；年报原文未单独披露该项同比，'
                '-3.94% 由用户人工核定（按此反推 2024 年末实缴职工约 40.37 万人）',
    },
}


def detect_indent(raw):
    indents = []
    for line in raw.split('\n'):
        m = re.match(r'^( +)\S', line)
        if m:
            indents.append(len(m.group(1)))
    return min(indents) if indents else 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    raw = open(DB, encoding='utf-8').read()
    indent = detect_indent(raw)
    eof_newline = raw.endswith('\n')
    db = json.loads(raw)

    cities = db['annual_reports']['cities']
    by_city = {c['city']: c for c in cities}
    changed = []

    for city, patch in PATCH.items():
        c = by_city.get(city)
        if c is None:
            print(f'!! 库中无此城市：{city}')
            continue
        entry = c.setdefault('stats_2025', {}).setdefault('active_employees', {})
        before = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        for k, v in patch.items():
            entry[k] = v
        order = ['value', 'unit', 'yoy', 'source_url', 'source_name', 'extract_method', 'note']
        merged = {k: entry[k] for k in order if k in entry}
        merged.update({k: v for k, v in entry.items() if k not in order})
        c['stats_2025']['active_employees'] = merged
        after = json.dumps(merged, ensure_ascii=False, sort_keys=True)
        if before != after:
            changed.append(city)

    n_emp = sum(1 for c in cities
                if (c.get('stats_2025', {}).get('active_employees') or {}).get('value') is not None)
    n_yoy = sum(1 for c in cities
                if (c.get('stats_2025', {}).get('active_employees') or {}).get('yoy'))
    db['version'] = NEW_VERSION

    out = json.dumps(db, ensure_ascii=False, indent=indent)
    if not eof_newline:
        out = out.rstrip('\n')

    print(f'改动城市：{changed}')
    print(f'active_employees 有值 {n_emp}/{len(cities)}｜有同比 {n_yoy}｜'
          f'version→{NEW_VERSION}｜indent={indent}')

    if args.apply:
        open(DB, 'w', encoding='utf-8').write(out)
        print(f'已写入 {DB}（eof_newline={eof_newline}）')
    else:
        diff = list(difflib.unified_diff(raw.split('\n'), out.split('\n'), lineterm='', n=0))
        print(f'dry-run: {len(diff)} 行 diff')
        for line in diff[:60]:
            print(line[:200])


if __name__ == '__main__':
    main()
