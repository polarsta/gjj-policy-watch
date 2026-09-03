# -*- coding: utf-8 -*-
"""
按《公积金运行数据_更新总结_剔除增减列_按城市归并_精简版.md》补录年报信息（2026-09-03 批次）。

覆盖 21 城，共 4 类字段：
  1) stats_2025.active_units.yoy     实缴单位同比
  2) stats_2025.deposit_amount.yoy   缴存额同比
  3) stats_2025.new_units / new_employees / fund_deposit_balance + 顶层 fund_deposit_change
  4) report_2025.url / report_2024.url 年报链接（替换为官方来源）

同时按项目既有口径（fund_deposit_change = 2025 存款 − 2024 存款）反填缺失的
stats_2024.fund_deposit_balance（仅在本批次给出「增减」且 2024 值缺失时）。
"""
import json
import os

ROOT = '/Users/xuyixuan/gjj-policy-watch'
TARGETS = [
    os.path.join(ROOT, 'gjj_policy_database.json'),       # 主库（git 跟踪）
    os.path.join(ROOT, 'app/db.json'),                     # 前端镜像（git 跟踪）
    os.path.join(ROOT, 'site/gjj_policy_database.json'),   # 部署镜像（NOT in git，需手动同步）
]

NEW_UPDATED_AT = '2026-09-03（补录21城2025年报实缴单位/缴存额同比、新开户、资金存款及增减，并替换18条年报链接为官方来源）'

# ---------------------------------------------------------------- 本批次数据
# 键: 城市名
#   yoy_units / yoy_deposit   → stats_2025 同比（字符串，带符号）
#   new_units / new_employees → stats_2025 新开户（家 / 万人）
#   fdb25                     → stats_2025.fund_deposit_balance（亿元）
#   fdc                       → 顶层 fund_deposit_change（亿元，正=增加 负=减少）
#   r25 / r24                 → {'url','title','publish_date'}，只写需要变更的键
PATCH = {
    '温州': {
        'yoy_units': '+3.16%', 'yoy_deposit': '+3.41%',
        'r25': {'url': 'https://zfgjj.wenzhou.gov.cn/col/col1229322000/art/2026/art_3dac019ecb6a456b821687aa7f74ecc5.html'},
    },
    '南通': {
        'yoy_deposit': '-8.07%',
        'r24': {'url': 'https://www.ntgjj.com/NewsDetail.aspx?DetailId=20857458'},
    },
    '舟山': {
        'fdc': 18.21,
        'r24': {'url': 'https://mp.weixin.qq.com/s?__biz=MzI4MTY2MjAxMA==&mid=2247893458&idx=2&sn=cddbb12a7814a25a52d6212650defe31&chksm=ea3021f1cf47ca2ab82fb234a5c653d8333dc4b6558403480359890e447b85bf9d919fe9f500&scene=27'},
    },
    '黄冈': {'yoy_units': '+1.79%', 'yoy_deposit': '-0.04%'},
    '荆州': {
        'new_units': 517, 'new_employees': 3.13,
        'yoy_units': '+7.30%', 'yoy_deposit': '+3.21%',
        'fdb25': 88.44, 'fdc': 15.97,
    },
    '洛阳': {
        'yoy_units': '+3.06%', 'yoy_deposit': '+2.95%',
        'r24': {'url': 'https://hnjs.henan.gov.cn/2025/04-30/3154030.html'},
    },
    '安阳': {
        'r24': {
            'url': 'https://hnjs.henan.gov.cn/2025/04-30/3154030.html',
            'title': '安阳市2024年数据（市级年报全文未检索到；取自河南省2024年年度报告）',
            'publish_date': '2025-04-30',
        },
    },
    '泸州': {
        'fdc': 14.97,
        'r24': {
            'url': 'https://zfgjj.luzhou.cn/zwgk/xxgknb/content_25206',
            'publish_date': '2025-03-24',
        },
    },
    '西安': {
        'r24': {'url': 'https://czt.shaanxi.gov.cn/xxgk/zdgk/lvyj/qywj/202504/t20250430_3510725.html'},
    },
    '榆林': {
        'yoy_units': '-2.96%',
        'r24': {'url': 'https://czt.shaanxi.gov.cn/xxgk/zdgk/lvyj/qywj/202504/t20250430_3510725.html'},
    },
    '咸阳': {
        'yoy_units': '-34.33%',
        'r24': {'url': 'https://czt.shaanxi.gov.cn/xxgk/zdgk/lvyj/qywj/202504/t20250430_3510725.html'},
    },
    '宝鸡': {'yoy_units': '-11.04%'},
    '曲靖': {'yoy_units': '+2.45%'},
    '红河': {
        'yoy_units': '+1.89%',
        'r25': {'url': 'https://www.hhgjj.com/website/annualReport-detail.html?seqno=610&itemId=0109'},
        'r24': {'url': 'https://www.hhgjj.com/website/annualReport-detail.html?seqno=536&itemId=0109'},
    },
    '遵义': {
        'yoy_units': '+1.09%', 'yoy_deposit': '+5.64%',
        'r25': {'url': 'https://zfgjj.zunyi.gov.cn/zxdt/tzgg/202603/t20260327_89916027.html'},
        'r24': {'url': 'https://zfgjj.zunyi.gov.cn/zxdt/tzgg/202503/t20250326_87272519.html'},
    },
    '银川': {'yoy_units': '+8.07%', 'yoy_deposit': '+7.74%'},
    '包头': {
        'yoy_units': '+3.02%', 'yoy_deposit': '+6.35%',
        'r25': {
            'url': 'https://www.btgjj.cn/?#/website/article/2918',
            'title': '包头市住房公积金2025年年度报告',
        },
    },
    '大连': {
        'new_units': 5935, 'new_employees': 7.93,
        'yoy_units': '+1.02%', 'yoy_deposit': '+4.01%',
        'r25': {
            'url': 'https://gjj.dl.gov.cn/art/2026/3/31/art_5566_2505635.html',
            'title': '大连市住房公积金2025年年度报告',
        },
    },
    '锦州': {
        'yoy_units': '+4.31%', 'yoy_deposit': '+6.66%',
        'r25': {'url': 'https://jzsgjj.cn/newsDetailsnew.jsp?newsid=31994&navid=3'},
        'r24': {'url': 'https://jzsgjj.cn/newsDetailsnew.jsp?newsid=31983&navid=3'},
    },
    '丹东': {
        'fdc': 13.54,
        'r25': {'url': 'https://www.ddzfgjj.com/gjjgb/38263.jhtml'},
        'r24': {
            'url': 'https://www.ddzfgjj.com/gjjgb/38081.jhtml',
            'title': '丹东市住房公积金2024年年度报告',
            'publish_date': '2025-03-28',
        },
    },
    '日照': {
        'yoy_units': '+2.40%', 'fdb25': 57.55, 'fdc': 18.76,
    },
}

# 需要按「2025 存款 − 增减」反填 2024 存款的城市（脚本内自动判定，此处仅作审计留痕）
DERIVE_FDB24 = ['舟山', '泸州', '丹东']


def apply(db, log):
    ar = db['annual_reports']
    idx = {c['city']: c for c in ar['cities']}
    for city, p in PATCH.items():
        c = idx.get(city)
        if c is None:
            log.append('!! 未找到城市：%s' % city)
            continue
        s5 = c.setdefault('stats_2025', {})
        s4 = c.setdefault('stats_2024', {})

        if 'yoy_units' in p:
            s5.setdefault('active_units', {'unit': '万家'})['yoy'] = p['yoy_units']
        if 'yoy_deposit' in p:
            s5.setdefault('deposit_amount', {'unit': '亿元'})['yoy'] = p['yoy_deposit']
        if 'new_units' in p:
            s5.setdefault('new_units', {'unit': '家'})['value'] = p['new_units']
        if 'new_employees' in p:
            s5.setdefault('new_employees', {'unit': '万人'})['value'] = p['new_employees']
        if 'fdb25' in p:
            s5.setdefault('fund_deposit_balance', {'unit': '亿元'})['value'] = p['fdb25']

        if 'fdc' in p:
            v = p['fdc']
            c['fund_deposit_change'] = {
                'value_yi': abs(v),
                'direction': '增加' if v >= 0 else '减少',
                'text': '%s%.2f亿元' % ('增加' if v >= 0 else '减少', abs(v)),
            }
            # 按项目既有口径反填缺失的 2024 存款余额
            fdb25 = (s5.get('fund_deposit_balance') or {}).get('value')
            fdb24 = (s4.get('fund_deposit_balance') or {}).get('value')
            if fdb25 is not None and fdb24 is None:
                s4['fund_deposit_balance'] = {
                    'value': round(fdb25 - v, 2),
                    'unit': '亿元',
                    'note': '由2025年报资金存款与较2024增减值反算',
                }
                log.append('%s stats_2024.fund_deposit_balance = %.2f（反算）' % (city, round(fdb25 - v, 2)))

        for key in ('r25', 'r24'):
            if key not in p:
                continue
            rep = c.get('report_2025' if key == 'r25' else 'report_2024') or {}
            old = rep.get('url')
            for k, v in p[key].items():
                rep[k] = v
            rep = {k: rep.get(k) for k in ('title', 'url', 'publish_date')}
            if key == 'r25':
                c['report_2025'] = rep
            else:
                c['report_2024'] = rep
            log.append('%s %s: %s → %s' % (city, key, old, rep['url']))

    ar['updated_at'] = NEW_UPDATED_AT
    return db


def main():
    log = []
    for path in TARGETS:
        with open(path, encoding='utf-8-sig') as f:
            db = json.load(f)
        apply(db, log)
        with open(path, 'w', encoding='utf-8-sig') as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        print('written: %s' % path)

    print('\n--- 变更明细 ---')
    for line in log:
        print(line)


if __name__ == '__main__':
    main()
