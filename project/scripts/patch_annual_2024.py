# -*- coding: utf-8 -*-
"""
把 2024 年报采集到的「提取额 / 发放贷款」回填到 annual_reports.cities[].stats_2024，
用于前端计算同比增幅与增减量。

取值优先级：
 1) 省级年报（洛阳等）→ 分城市表格中本市那一行
 2) 市级年报正文「（二）提取 /（三）贷款」章节全市口径值（早于"其中"分中心拆解）
 3) 人工核验补录（MANUAL：年报原文经 WebFetch 人工摘录，已在 note 标注）

未取到的城市不写入任何数值，在 note 中记录缺失原因（前端显示「—」待补）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_annual_2024 import DB

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAND = os.path.join(ROOT, 'project', 'data', 'annual_2024_candidates.json')
APP_DB = os.path.join(ROOT, 'app', 'db.json')
TODO = os.path.join(ROOT, 'project', 'data', 'annual_2024_todo.json')

# 人工核验补录：经 WebFetch 从年报原文逐字摘录（m12333/政务站被 WAF 拦截，改用服务端抓取）
MANUAL = {
    '天津': {
        'withdraw_amount': {'value': 568.48, 'quote': '2024年，132.35万名缴存职工提取住房公积金；提取额568.48亿元，同比降低1.89%'},
        'loan_issued': {'value': 372.52, 'quote': '2024年，发放个人住房贷款5.51万笔372.52亿元，贷款金额同比增长12.2%'},
        'source_name': '天津市住房公积金2024年年度报告（天津市住房公积金管理中心官网）',
    },
}

REASON = {
    'NO_URL': '无2024年报链接',
    'JS_RENDER': '年报页为JS渲染/附件下载，正文未取到',
    'NOT_DISCLOSED': '年报未披露该指标',
}


def reason_of(rec):
    if not rec or not rec.get('ok'):
        err = (rec or {}).get('err', '')
        if 'NO_URL' in err:
            return '无2024年报链接'
        if 'JS_RENDER' in err or 'NO_SNAPSHOT' in err:
            return '年报链接失效或WAF拦截，未能取到原文'
        return f'年报原文抓取失败（{err[:40]}）'
    return '年报正文未匹配到该指标表述'


def main():
    cand = {r['city']: r for r in json.load(open(CAND, encoding='utf-8'))}
    db = json.load(open(DB, encoding='utf-8-sig'))
    ar = db['annual_reports']
    filled = miss = 0
    miss_list = []
    for x in ar['cities']:
        city = x['city']
        rec = cand.get(city, {})
        s24 = x.setdefault('stats_2024', {})
        r24 = x.get('report_2024') or {}
        src_url, src_name = r24.get('url', ''), r24.get('title', '')
        got = {}
        for key, cand_key in (('withdraw_amount', 'withdraw'), ('loan_issued', 'loan')):
            val, method = None, ''
            t = rec.get(cand_key + '_table')
            if t and t.get('value'):
                val, method = t['value'], '省级年报分市表'
            elif rec.get(cand_key):
                val, method = rec[cand_key][0]['value'], '年报正文'
            if city in MANUAL and key in MANUAL[city]:
                val, method = MANUAL[city][key]['value'], '年报原文人工核验'
            if val is None:
                continue
            item = {'value': val, 'unit': '亿元'}
            if src_url:
                item['source_url'] = src_url
            item['source_name'] = MANUAL.get(city, {}).get('source_name') or src_name
            item['extract_method'] = method
            s24[key] = item
            got[key] = {'value': val, 'method': method}
        if got:
            filled += 1
        else:
            miss += 1
            miss_list.append({'city': city, 'reason': reason_of(rec), 'url': src_url})
        # note 追加口径说明
        if got:
            note = x.get('note') or ''
            labels = '、'.join('提取额' if k == 'withdraw_amount' else '发放贷款' for k in got)
            methods = {v['method'] for v in got.values()}
            mstr = '省级年报分市表' if '省级年报分市表' in methods else (
                '年报原文人工核验' if '年报原文人工核验' in methods else '年报正文')
            add = f'2024年{labels}取自2024年报（{mstr}），同比与增减量由2025/2024绝对值计算。'
            if '2024年提取额' not in note:
                x['note'] = (note + add).strip()
        else:
            note = x.get('note') or ''
            add = f'2024年提取额/发放贷款未取到（{reason_of(rec)}），待补。'
            if '未取到' not in note:
                x['note'] = (note + add).strip()
    ar['description'] = ('134城住房公积金年度报告静态数据库：2025年报+2024年报原文链接及年度统计数据'
                         '（缴存/提取/贷款/资金存款）。2024年提取额与发放贷款字段为2026-09-02补录，'
                         '取自各市2024年年度报告原文（或省级年报分市表），用于计算同比增幅与增减量；'
                         '未取到的城市留空，前端显示「—」待补。本模块为历史统计数据，不随每周任务自动更新。')
    ar['updated_at'] = '2026-09-02'
    ar['yoy_note'] = ('提取额 / 发放贷款的「同比±X%」与「▲增加 / ▼减少 X 亿元」'
                      '均以 stats_2025 与 stats_2024 的绝对值口径自行计算，非年报原文直接披露值')
    json.dump(db, open(DB, 'w', encoding='utf-8-sig'), ensure_ascii=False, indent=2)
    # 同步 app/db.json 的同一模块
    app = json.load(open(APP_DB, encoding='utf-8-sig'))
    app['annual_reports'] = ar
    json.dump(app, open(APP_DB, 'w', encoding='utf-8-sig'), ensure_ascii=False, indent=2)
    json.dump(miss_list, open(TODO, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'回填完成：有2024数据 {filled} 城，待补 {miss} 城')
    print('待补示例：', miss_list[:5])


if __name__ == '__main__':
    main()
