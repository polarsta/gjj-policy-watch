# -*- coding: utf-8 -*-
"""
把 45 城 2024 年「提取额 / 发放个人住房贷款」回填到主库。

- 数据源：project/data/annual_45_patch.json（每条都带 source_url / source_name / type）
- 写回：gjj_policy_database.json（主库）与 app/db.json（前端镜像）
- 编码：UTF-8-SIG（项目约定；CSV/JSON 必须带 BOM）
- 幂等：重复执行结果一致；已存在的同值条目不会重复追加
"""
import json
import os
import sys
import shutil
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # gjj-policy-watch
PROJ = os.path.dirname(HERE)                          # gjj-policy-watch/project
PATCH = os.path.join(PROJ, 'data', 'annual_45_patch.json')
DBS = [
    os.path.join(ROOT, 'gjj_policy_database.json'),
    os.path.join(ROOT, 'app', 'db.json'),
]


def load(p):
    with open(p, encoding='utf-8-sig') as f:
        return json.load(f)


def save(p, obj):
    bak = p + '.bak'
    if not os.path.exists(bak):
        shutil.copy2(p, bak)
    with open(p, 'w', encoding='utf-8-sig') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def apply(db, patch, report):
    cities = db.get('annual_reports', {}).get('cities', [])
    idx = {c['city']: c for c in cities}
    for city, row in patch.items():
        if city.startswith('_'):
            continue
        w, l = row.get('w'), row.get('l')
        if not w or not l:
            report['skipped'].append(f'{city}（无可用数据：{row.get("note", "")}）')
            continue
        obj = idx.get(city)
        if obj is None:
            report['missing_city'].append(city)
            continue
        s24 = obj.setdefault('stats_2024', {})
        method = '省级年报分市表' if row.get('kind') == 'provincial' else '年报正文'
        s24['withdraw_amount'] = {
            'value': w, 'unit': '亿元',
            'source_url': row['url'], 'source_name': row['name'],
            'extract_method': method,
        }
        s24['loan_issued'] = {
            'value': l, 'unit': '亿元',
            'source_url': row['url'], 'source_name': row['name'],
            'extract_method': method,
        }
        report['patched'].append(city)
    # 更新时间戳
    ar = db.get('annual_reports', {})
    if isinstance(ar, dict):
        ar['updated_at'] = datetime.now().strftime('%Y-%m-%d') + '（补录45城2024年提取额/发放贷款，来源均为官方年报）'
    return db


def main():
    patch = json.load(open(PATCH, encoding='utf-8'))
    for p in DBS:
        if not os.path.exists(p):
            print(f'跳过（不存在）：{p}')
            continue
        db = load(p)
        report = {'patched': [], 'skipped': [], 'missing_city': []}
        db = apply(db, patch, report)
        save(p, db)
        print(f'\n=== {os.path.relpath(p, ROOT)} ===')
        print(f'  写入 {len(report["patched"])} 城；跳过 {len(report["skipped"])} 城')
        if report['skipped']:
            for s in report['skipped']:
                print(f'    - {s}')
        if report['missing_city']:
            print(f'  库中不存在：{report["missing_city"]}')


if __name__ == '__main__':
    main()
