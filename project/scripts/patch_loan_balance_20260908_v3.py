# -*- coding: utf-8 -*-
"""
2025 年报贷款余额 + 同比 —— 第三轮补丁（2026-09-08 用户人工复核后定点修正）。

仅改 4 城，其余城市原样保留：
  1. 洛阳 2964.23 → **283.43** 亿元，yoy → **-0.58%**
     （2964.23 为《河南省 2025 年年度报告》全省口径，系误取；
       正确值 283.43 出自同一报告「表3 2025年分城市住房公积金个人住房贷款情况」洛阳市行）
  2. 大连 yoy null → **+1.41%**（年报未披露，按 2024 年末余额 736.00 亿元计算，用户人工核对确认）
  3. 衢州 / 镇江：维持年报原文口径（-0.86% / -6.8%），用户已确认，note 补记确认状态

版本号 1.5.7 → 1.5.8。写库遵循项目规范：detect_indent 取全文件最小正缩进（主库=1 空格）、
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

NEW_VERSION = '1.5.8'

HENAN_URL = 'https://hnjs.henan.gov.cn/2026/04-30/3347933.html'

PATCH = {
    '洛阳': {
        'value': 283.43,
        'yoy': '-0.58%',
        'source_url': HENAN_URL,
        'source_name': '河南省住房公积金2025年年度报告（表3 分城市住房公积金个人住房贷款情况）',
        'extract_method': '河南省年报分城市表（用户核定 2026-09-08）',
        'note': '此前 2964.23 亿元为河南省全省口径（误取），已更正为洛阳市级 283.43 亿元；'
                '出自《河南省住房公积金2025年年度报告》表3「2025年分城市住房公积金个人住房贷款情况」。'
                '洛阳市级年报全文仍待从洛阳中心官方渠道补链',
    },
    '大连': {
        'yoy': '+1.41%',
        'extract_method': '年报正文 + 按 2024 年报余额计算（用户人工核对 2026-09-08）',
        'note': '年报原文未披露贷款余额同比；按 2024 年末余额 736.00 亿元计算得 +1.41%，'
                '已于 2026-09-08 经人工核对确认',
    },
    '衢州': {
        'note': '年报原文：贷款余额 159.43 亿元，比上年末下降 0.86%'
                '（句中「分别增加 2.66%、5.67%」为累计发放笔数与金额的同比，非余额同比）；'
                '已于 2026-09-08 经用户确认按此口径入库',
    },
    '镇江': {
        'note': '年报原文：贷款余额 156.30 亿元，同比下降 6.8%'
                '（句中「分别增加 2.14%、3.85%」为累计发放笔数与金额的同比，非余额同比）；'
                '已于 2026-09-08 经用户确认按此口径入库',
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
        entry = c.setdefault('stats_2025', {}).setdefault('loan_balance', {})
        before = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        for k, v in patch.items():
            entry[k] = v
        # 字段顺序：value/unit/yoy/source_url/source_name/extract_method/note
        order = ['value', 'unit', 'yoy', 'source_url', 'source_name', 'extract_method', 'note']
        entry = {k: entry[k] for k in order if k in entry}
        entry.update({k: v for k, v in entry.items() if k not in order})
        c['stats_2025']['loan_balance'] = entry
        after = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        if before != after:
            changed.append(city)

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
        diff = list(difflib.unified_diff(raw.split('\n'), out.split('\n'),
                                         lineterm='', n=0))
        print(f'dry-run: {len(diff)} 行 diff')
        for line in diff[:60]:
            print(line[:200])


if __name__ == '__main__':
    main()
