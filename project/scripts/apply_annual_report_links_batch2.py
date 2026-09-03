# -*- coding: utf-8 -*-
"""
第二批年报链接更新：9 城 12 条（来源 Excel：第二次-更新40城链接-标红.xlsx）

用法：
    python project/scripts/apply_annual_report_links_batch2.py            # dry-run
    python project/scripts/apply_annual_report_links_batch2.py --apply    # 落盘

要点：
1. 主库原始缩进是 indent=1，重写必须保持一致，否则 diff 会炸到十几万行。
2. 同步替换 stats_YYYY.*.source_url 中指向旧链接的引用，避免同一条数据挂两个来源。
3. 落盘前自动备份 gjj_policy_database.json.bak_<日期>。
4. 输出变更清单到 project/data/annual_report_links_batch2_applied.json。
"""
import json
import os
import re
import shutil
import sys
import datetime

import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXCEL = '/Users/xuyixuan/Downloads/第二次-更新40城链接-标红.xlsx'
DB = os.path.join(ROOT, 'gjj_policy_database.json')
CHECKED_AT = '2026-09-03'

# 人工修正：城市+年度 -> 新链接（覆盖 Excel 中的值）。本次无需修正，留空备用。
CORRECTIONS = {}

# 仅标题需要订正的情况（旧标题描述的是上一版来源，会误导）
TITLE_FIX = {
    ('丽江', 2025): '丽江市住房公积金2025年年度报告（搜狐转载，图片版；'
                    '核心数据已与云南省住房公积金2025年年度报告分城市表交叉核对）',
}

# 域名 -> 来源类型（沿用 negative_news 的四分类口径）
DOMAIN_SOURCE_TYPE = {
    'ycgjj.yancheng.gov.cn': '政府网站',
    'zfgjj.luzhou.cn':       '政府网站',
    'www.sohu.com':          '其他媒体',
    'szb.lijiang.cn':        '官方媒体',   # 丽江日报数字报（党报）
    'www.xjbtgjj.com':       '政府网站',
    'www.jjszfgjj.cn':       '政府网站',
    'www.leshan.gov.cn':     '政府网站',
    'www.zf365.com.cn':      '政府网站',   # 朔州市住房公积金管理中心门户网站
    'qianfan.weijj.cn':      '其他媒体',   # 微靖江（地方自媒体）
    'gjj.zhuzhou.gov.cn':    '政府网站',
}


def norm(s):
    return str(s or '').replace('市', '').replace(' ', '')


def domain_of(url):
    return re.sub(r'^https?://', '', str(url or '')).split('/')[0]


def main():
    apply = '--apply' in sys.argv

    wb = openpyxl.load_workbook(EXCEL, data_only=True)
    rows = list(wb['Sheet1'].iter_rows(min_row=2, values_only=True))

    db = json.loads(open(DB, encoding='utf-8-sig').read())
    cities = db['annual_reports']['cities']
    n2c = {}
    for c in cities:
        n2c.setdefault(norm(c['city']), []).append(c)

    changes, unchanged = [], []

    for city, u25, u24 in rows:
        if not city:
            continue
        key = norm(city)
        m = n2c.get(key)
        if not m:
            print('!! 未匹配城市：%s' % city)
            continue
        if len(m) > 1:
            print('!! 多匹配：%s -> %s' % (city, [x['city'] for x in m]))
        c = m[0]

        for year, raw in ((2025, u25), (2024, u24)):
            new = str(raw).strip() if raw else None
            new = CORRECTIONS.get((city, year), new)
            if not new:
                unchanged.append((city, year, 'Excel 未提供链接', (c.get('report_%s' % year) or {}).get('url')))
                continue

            rk = 'report_%s' % year
            r = c.setdefault(rk, {})
            old = r.get('url')

            if old == new:
                unchanged.append((city, year, '与库内一致', old))
                continue

            src_type = DOMAIN_SOURCE_TYPE.get(domain_of(new), '其他媒体')
            rec = {
                'city': city,
                'year': year,
                'old_url': old,
                'new_url': new,
                'source_type': src_type,
                'old_domain': domain_of(old) if old else None,
                'new_domain': domain_of(new),
            }

            # 1) 主链接
            r['url'] = new
            r['source_type'] = src_type
            r['verify'] = {'status': 'OK', 'checked_at': CHECKED_AT}

            # 2) 标题订正（仅登记在 TITLE_FIX 中的）
            if (city, year) in TITLE_FIX:
                rec['old_title'] = r.get('title')
                rec['new_title'] = TITLE_FIX[(city, year)]
                r['title'] = TITLE_FIX[(city, year)]

            # 3) 同步 stats_YYYY.*.source_url
            #    注意：old 为空时不回填——value 为 null 的字段（如 fund_deposit_balance）
            #    挂上来源会造成「有来源却无数据」的假象，全库惯例也是留空。
            synced = []
            if old:
                st = c.get('stats_%s' % year) or {}
                for f, v in st.items():
                    if isinstance(v, dict) and v.get('source_url') == old:
                        v['source_url'] = new
                        synced.append(f)
            rec['stats_synced'] = synced

            changes.append(rec)
            print('[%s %s] %s -> %s (%s)%s'
                  % (city, year, old or '(空)', new, src_type,
                     '  +stats:' + ','.join(synced) if synced else ''))

    print('\n变更 %d 条，未变更 %d 条' % (len(changes), len(unchanged)))
    for city, year, reason, url in unchanged:
        print('  跳过 %s %s：%s（现有 %s）' % (city, year, reason, url))

    if not apply:
        print('\n[DRY-RUN] 未写入。加 --apply 落盘。')
        return

    # 备份
    today = datetime.date.today().isoformat()
    bak = DB + '.bak_' + today
    if not os.path.exists(bak):
        shutil.copy2(DB, bak)
        print('\n已备份 -> %s' % os.path.basename(bak))
    else:
        print('\n备份已存在，跳过：%s' % os.path.basename(bak))

    # 元数据
    db['annual_reports']['updated_at'] = (
        '2026-09-03（两批共核验更新59条年报链接：第一批40城47条，第二批9城12条）'
    )
    old_v = db.get('version')
    assert old_v == '1.5.2', '主库版本预期 1.5.2（PR #16 合入后），实际 %s' % old_v
    db['version'] = '1.5.3'
    print('version: %s -> %s' % (old_v, db['version']))

    # 保持原始 indent=1
    with open(DB, 'w', encoding='utf-8-sig') as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    print('已写入主库（indent=1）')

    out = {
        'batch': 2,
        'source_excel': EXCEL,
        'checked_at': CHECKED_AT,
        'changes': changes,
        'unchanged': unchanged,
    }
    op = os.path.join(ROOT, 'project/data/annual_report_links_batch2_applied.json')
    json.dump(out, open(op, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('变更清单 -> %s' % os.path.relpath(op, ROOT))


if __name__ == '__main__':
    main()
