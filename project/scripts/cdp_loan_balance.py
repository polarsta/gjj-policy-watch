# -*- coding: utf-8 -*-
"""
用 CDP 无头 Chrome 渲染直连失败的 2025 年报页，文本落盘到
loan_balance_2025_txt/<城市>.txt，供 fetch_loan_balance_2025.py 缓存复用再解析。
"""
import sys
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cdp_fetch

ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
DB = os.path.join(REPO, 'gjj_policy_database.json')
OUTDIR = os.path.join(ROOT, 'data', 'loan_balance_2025_txt')

# 直连失败、需要浏览器渲染的城市
CITIES = ['深圳', '兰州', '台州', '合肥', '潍坊', '丽江', '日照',
          '唐山', '呼和浩特', '包头', '廊坊', '清远', '衡阳', '成都',
          '天津', '株洲', '重庆']


def main():
    db = json.load(open(DB, encoding='utf-8'))
    cities = {c['city']: c for c in db['annual_reports']['cities']}
    urls, order = {}, []
    for city in CITIES:
        url = ((cities.get(city) or {}).get('report_2025') or {}).get('url')
        if url:
            urls[url] = city
            order.append(url)
        else:
            print(f'{city}: 无链接，跳过')

    os.makedirs(OUTDIR, exist_ok=True)
    res = cdp_fetch.batch(order, wait=6.0, outdir=os.path.join(ROOT, 'data', 'loan_cdp_2025'))
    print()
    for url, r in res.items():
        city = urls[url]
        txt = r.get('text') or ''
        hit = '贷款余额' in txt or '个人住房贷款' in txt
        print(f'{city}: {len(txt)} 字符 命中={hit} {r.get("error", "")}')
        if txt and hit:
            with open(os.path.join(OUTDIR, f'{city}.txt'), 'w', encoding='utf-8') as f:
                f.write(txt)


if __name__ == '__main__':
    main()
