# -*- coding: utf-8 -*-
"""
2025 年报贷款余额 + 同比 —— 第四轮补丁（2026-09-08 用户人工复核：大庆）。

大庆：value 187.72 亿元（原有），yoy null → **-7.20%**
  年报原文未披露同比；按 2024 年末贷款余额 202.29 亿元计算：
  (187.72 - 202.29) / 202.29 = -7.20%，已于 2026-09-08 经用户人工核对确认。

版本号 1.5.8 → 1.5.9。写库遵循项目规范：detect_indent 取全文件最小正缩进（主库=1 空格）、
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

NEW_VERSION = '1.5.9'

PATCH = {
    '大庆': {
        'yoy': '-7.20%',
        'source_name': '大庆市住房公积金2025年数据（市级年报全文未检索到；取自黑龙江省2025年年度报告）',
        'extract_method': '年报正文 + 按 2024 年报余额计算（用户人工核对 2026-09-08）',
        'note': '年报原文未披露贷款余额同比；按 2024 年末余额 202.29 亿元计算得 -7.20%，'
                '已于 2026-09-08 经人工核对确认',
    },
}

# 顺带补全：report_2025.title 为 null（写库时 loan_balance.source_name 取自该字段）
REPORT_TITLE = {
    '大庆': '大庆市住房公积金2025年数据（市级年报全文未检索到；取自黑龙江省2025年年度报告）',
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
        entry = c.setdefault('stats_2025', {}).setdefault('loan_balance', {})
        before = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        for k, v in patch.items():
            entry[k] = v
        order = ['value', 'unit', 'yoy', 'source_url', 'source_name', 'extract_method', 'note']
        merged = {k: entry[k] for k in order if k in entry}
        merged.update({k: v for k, v in entry.items() if k not in order})
        c['stats_2025']['loan_balance'] = merged
        after = json.dumps(merged, ensure_ascii=False, sort_keys=True)
        if before != after:
            changed.append(city)

    for city, title in REPORT_TITLE.items():
        c = by_city.get(city)
        rpt = (c or {}).setdefault('report_2025', {}) or {}
        if not rpt.get('title'):
            rpt['title'] = title
            changed.append(f'{city}(report_2025.title)')

    n_ok = sum(1 for c in cities
               if (c.get('stats_2025', {}).get('loan_balance') or {}).get('value') is not None)
    n_yoy = sum(1 for c in cities
                if (c.get('stats_2025', {}).get('loan_balance') or {}).get('yoy'))
    db['version'] = NEW_VERSION

    out = json.dumps(db, ensure_ascii=False, indent=indent)
    if not eof_newline:
        out = out.rstrip('\n')

    print(f'改动城市：{changed}')
    print(f'有值 {n_ok}/{len(cities)}｜有同比 {n_yoy}｜version→{NEW_VERSION}｜indent={indent}')

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
