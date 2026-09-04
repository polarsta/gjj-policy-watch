#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「允许缓缴年限」补录结果清单（MD + CSV，UTF-8-SIG）。"""
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
ROOT = os.path.dirname(PROJ)
OUT_DIR = os.path.join(PROJ, 'data', 'out')
os.makedirs(OUT_DIR, exist_ok=True)


def defer_period(mp):
    t = str(mp or '').strip()
    if not t:
        return '待核实'
    if re.search(r'未检索到|未明确|未见明文|未注明|未单列|未在检索结果中明确', t) \
            and not re.search(r'不超过|不得超过|最长', t):
        return '待核实'
    if re.search(r'两年|24\s*个?月|(?:不超过|不得超过|最长)[^，。；]{0,4}(?<!\d)2\s*年', t):
        return '≤2年'
    if re.search(r'12\s*个月', t) and not re.search(r'12\s*个?月31日|至.{0,8}12\s*月', t):
        return '≤12个月'
    if re.search(r'一年|(?<!\d)1\s*年|一个住房公积金(结算)?年度|一个公积金年度|按缴存年度申请', t):
        return '≤1年'
    m = re.search(r'(\d+)\s*个?月', t)
    if m and not re.search(r'\d{4}\s*年', t[:t.index(m[0])]):
        return '≤%s个月' % m[1]
    if re.search(r'半年|6\s*个?月', t) and not re.search(r'2022年6月', t):
        return '≤6个月'
    return '待核实'


def main():
    with open(os.path.join(ROOT, 'gjj_policy_database.json'), encoding='utf-8-sig') as f:
        db = json.load(f)

    rows = []
    for c in db['cities']:
        dp = (c.get('deposit') or {}).get('deferred_payment') or {}
        mp = dp.get('max_period')
        rows.append({
            'city': c['city'],
            'province': c.get('province', ''),
            'supported': {True: '支持', False: '不支持'}.get(dp.get('supported'), '未标注'),
            'period': defer_period(mp),
            'max_period': mp or '',
            'has_procedure': '有' if dp.get('procedure') else '无',
            'has_rights': '有' if dp.get('employee_rights') else '无',
            'source_name': dp.get('source_name', ''),
            'source_url': dp.get('source_url', ''),
        })

    ok = [r for r in rows if r['period'] != '待核实']
    todo = [r for r in rows if r['period'] == '待核实']

    # ---------- CSV ----------
    csv_path = os.path.join(OUT_DIR, '公积金缓缴年限补录清单_20260904.csv')
    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['城市', '省份', '是否支持缓缴', '允许缓缴年限', '期限原文',
                    '办理流程', '职工权益说明', '来源名称', '来源链接'])
        for r in rows:
            w.writerow([r['city'], r['province'], r['supported'], r['period'], r['max_period'],
                        r['has_procedure'], r['has_rights'], r['source_name'], r['source_url']])

    # ---------- MD ----------
    dist = {}
    for r in rows:
        dist[r['period']] = dist.get(r['period'], 0) + 1
    order = ['≤6个月', '≤12个月', '≤1年', '≤2年', '待核实']

    md = []
    md.append('# 公积金「允许缓缴年限」补录结果（2026-09-04）\n')
    md.append('## 一、结论\n')
    md.append(f'- 覆盖 **{len(rows)} 城**，其中 **{len(ok)} 城**已能给出明确缓缴年限，'
              f'**{len(todo)} 城**仍显示「待核实」。\n')
    md.append('- 本次为**修复性回填**：2026-09-01 矩阵集成时把顶层 `deferral` 合并进 '
              '`deposit.deferred_payment`，漏搬了 `max_period` 字段，'
              '导致该列在此前 134 城全部显示「待核实」。\n')
    md.append('\n| 展示值 | 城市数 |\n|---|---|\n')
    for k in order:
        if k in dist:
            md.append(f'| {k} | {dist[k]} |\n')
    for k in dist:
        if k not in order:
            md.append(f'| {k} | {dist[k]} |\n')

    md.append('\n## 二、仍待核实的 %d 城\n' % len(todo))
    md.append('分两类：① 原文确无期限规定（公开渠道查不到）；'
              '② 有阶段性政策表述但非现行常规期限。\n\n')
    md.append('| 城市 | 省份 | 缓缴年限 | 期限原文/说明 |\n|---|---|---|---|\n')
    for r in todo:
        txt = (r['max_period'] or '（数据库暂无期限文本）').replace('|', '／').replace('\n', ' ')
        md.append(f"| {r['city']} | {r['province']} | {r['period']} | {txt[:90]} |\n")

    md.append('\n## 三、已明确的城市（节选 40 城）\n')
    md.append('| 城市 | 省份 | 缓缴年限 | 期限原文（节选） |\n|---|---|---|---|\n')
    for r in ok[:40]:
        txt = (r['max_period'] or '').replace('|', '／').replace('\n', ' ')
        md.append(f"| {r['city']} | {r['province']} | {r['period']} | {txt[:70]} |\n")
    if len(ok) > 40:
        md.append(f'\n（其余 {len(ok) - 40} 城见 CSV 全量清单）\n')

    md.append('\n## 四、数据来源与口径\n')
    md.append('- 数据取自各市住房公积金管理中心官网 / 政府门户发布的现行缓缴规定，'
              '字段原文保存在 `deposit.deferred_payment.max_period`。\n')
    md.append('- 展示值由前端 `deferPeriod()` 从原文提炼，规则：'
              '≤6个月 / ≤12个月 / ≤1年 / ≤2年 / 待核实。\n')
    md.append('- 同期一并恢复了 `procedure`（办理流程）与 `employee_rights`（对职工权益的影响），'
              '这两项此前也在同一次合并中丢失。\n')
    md.append('- 「待核实」不填推测值；如需补录，需逐城检索当地最新缓缴文件。\n')

    md_path = os.path.join(OUT_DIR, '公积金缓缴年限补录清单_20260904.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(''.join(md))

    print('已生成：')
    print(' ', md_path)
    print(' ', csv_path)
    print()
    print('展示分布：', {k: dist[k] for k in order if k in dist})
    print('待核实 %d 城：' % len(todo), '、'.join(r['city'] for r in todo))


if __name__ == '__main__':
    main()
