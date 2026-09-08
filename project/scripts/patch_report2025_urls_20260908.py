# -*- coding: utf-8 -*-
"""
更新 10 个城市 2025 年年报链接（用户 2026-09-08 提供）。

写库遵循项目规范：detect_indent 取全文件最小正缩进（主库=1 空格）、
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

# 用户 2026-09-08 提供的官方年报地址
URLS = {
    '合肥': ('合肥市住房公积金2025年年度报告',
             'https://gjjzx.hefei.gov.cn/public/4311/112577627.html'),
    '黄冈': ('黄冈住房公积金2025年年度报告',
             'https://gjj.hg.gov.cn/zwgk/public/6636168/1707824.html'),
    '孝感': ('孝感市住房公积金2025年年度报告',
             'https://xggjj.xiaogan.gov.cn/zwgk/2116927.jhtml'),
    '荆州': ('荆州住房公积金2025年年度报告',
             'http://gjj.zwgk.jingzhou.gov.cn/35035/103220263/t127220263034/681265.shtml'),
    '株洲': ('株洲市住房公积金2025年年度报告',
             'https://gjj.zhuzhou.gov.cn/c5361/20260327/i2486539.html'),
    '衡阳': ('衡阳市住房公积金2025年年度报告',
             'https://www.hengyang.gov.cn/hyszfgjj/xxgk/ghjh/20260330/i3879763.html'),
    '娄底': ('娄底市住房公积金2025年年度报告',
             'https://www.ldgjj.com/detailsList/1865.html'),
    '兰州': ('兰州市住房公积金2025年年度报告',
             'https://gjj.lanzhou.gov.cn/art/2026/3/31/art_412_1691387.html'),
    '哈尔滨': ('哈尔滨市住房公积金2025年年度报告',
               'https://www.hrbgjj.org.cn/ndbg/2416.jhtml'),
    '日照': ('日照市住房公积金2025年年度报告',
             'https://www.rizhaozfgjj.cn/art/2026/3/26/art_182478_10283356.html'),
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

    cities = {c['city']: c for c in db['annual_reports']['cities']}
    changed = []
    for city, (title, url) in URLS.items():
        c = cities.get(city)
        if not c:
            print(f'!! 库中无此城市: {city}')
            continue
        rpt = c.setdefault('report_2025', {})
        old = rpt.get('url')
        if old == url and rpt.get('title') == title:
            continue
        rpt['title'] = title
        rpt['url'] = url
        changed.append((city, old, url))

    out = json.dumps(db, ensure_ascii=False, indent=indent)
    if not eof_newline:
        out = out.rstrip('\n')

    print(f'待更新 {len(changed)} 个城市：')
    for city, old, new in changed:
        print(f'  {city}: {str(old)[:60]} -> {new[:70]}')

    if args.apply:
        open(DB, 'w', encoding='utf-8').write(out)
        print(f'已写入（indent={indent}, eof_newline={eof_newline}）')
    else:
        diff = list(difflib.unified_diff(raw.split('\n'), out.split('\n'), lineterm='', n=0))
        print(f'dry-run: {len(diff)} 行 diff')


if __name__ == '__main__':
    main()
