# -*- coding: utf-8 -*-
"""按《公积金运行数据_更新总结_剔除增减列_按城市归并_精简版.md》逐条核验数据库。

只读校验，不改数据。输出 PASS/MISS 明细 + 汇总。
"""
import json
import re
import sys

DOC = '/Users/xuyixuan/Downloads/公积金运行数据_更新总结_剔除增减列_按城市归并_精简版.md'
DB = '/Users/xuyixuan/gjj-policy-watch/gjj_policy_database.json'

CN_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5}


def parse_doc(path):
    """返回 [(city, [(field, value, url_or_None), ...]), ...]"""
    city = None
    out = []
    for line in open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        m = re.match(r'^###\s*\d+\.\s*(\S+)\s*$', line)
        if m:
            city = m.group(1)
            out.append((city, []))
            continue
        if city is None or not line.startswith('- '):
            continue
        body = line[2:].strip()
        # 字段: 值
        m = re.match(r'^(实缴单位同比|缴存额同比|新开户单位（家）|新开户职工（万人）|'
                     r'资金存款2025（亿元）|资金存款较2024增减（亿元）)\s*[:：]\s*(.+)$', body)
        if m:
            out[-1][1].append((m.group(1), m.group(2).strip(), None))
            continue
        m = re.match(r'^(\d{4})年报(?:链接)?\s*(?:→)?\s*(https?://\S+?)(?:（.*)?$', body)
        if m:
            out[-1][1].append(('年报链接', m.group(2).strip(), m.group(1)))
    return out


def norm_pct(s):
    """'3.16%' / '-8.07%' / '3.16' -> float"""
    s = str(s).replace('%', '').replace('+', '').strip()
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def norm_db_pct(v):
    """DB 里的 yoy 可能是 '+3.16%' / '3.16%' / 3.16"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return norm_pct(v)


def main():
    db = json.load(open(DB, encoding='utf-8-sig'))
    cities = {c['city']: c for c in db['annual_reports']['cities']}
    doc = parse_doc(DOC)

    total = ok = 0
    miss = []
    for city, rows in doc:
        c = cities.get(city)
        if c is None:
            miss.append((city, '城市不存在', '', ''))
            continue
        s5 = c.get('stats_2025') or {}
        for field, val, year in rows:
            total += 1
            if field == '实缴单位同比':
                got = norm_db_pct((s5.get('active_units') or {}).get('yoy'))
                want = norm_pct(val)
                if got == want:
                    ok += 1
                else:
                    miss.append((city, field, want, got))
            elif field == '缴存额同比':
                got = norm_db_pct((s5.get('deposit_amount') or {}).get('yoy'))
                want = norm_pct(val)
                if got == want:
                    ok += 1
                else:
                    miss.append((city, field, want, got))
            elif field == '新开户单位（家）':
                got = (s5.get('new_units') or {}).get('value')
                want = int(float(val))
                if got == want:
                    ok += 1
                else:
                    miss.append((city, field, want, got))
            elif field == '新开户职工（万人）':
                got = (s5.get('new_employees') or {}).get('value')
                want = float(val)
                if got is not None and abs(got - want) < 1e-6:
                    ok += 1
                else:
                    miss.append((city, field, want, got))
            elif field == '资金存款2025（亿元）':
                got = (s5.get('fund_deposit_balance') or {}).get('value')
                want = float(val)
                if got is not None and abs(got - want) < 1e-6:
                    ok += 1
                else:
                    miss.append((city, field, want, got))
            elif field == '资金存款较2024增减（亿元）':
                fdc = c.get('fund_deposit_change') or {}
                got = fdc.get('value_yi')
                want = float(val)
                if got is not None and abs(got - want) < 1e-6:
                    ok += 1
                else:
                    miss.append((city, field, want, got))
            elif field == '年报链接':
                rep = c.get('report_%s' % year) or {}
                got = (rep.get('url') or '').strip()
                if got == val:
                    ok += 1
                else:
                    miss.append((city, '%s年报链接' % year, val[:60] + '...', got[:60] + '...'))

    print('=' * 70)
    print('文档条目总数：%d | 已正确落库：%d | 未命中：%d' % (total, ok, len(miss)))
    print('=' * 70)
    if miss:
        print('%-6s %-26s %-22s %s' % ('城市', '字段', '文档值', '数据库值'))
        for city, field, want, got in miss:
            print('%-6s %-26s %-22s %s' % (city, field, str(want)[:20], str(got)[:20]))
    else:
        print('全部条目均已正确落库 ✅')

    # 附加：全局聚合站链接残留
    agg = sorted({c['city'] for c in db['annual_reports']['cities']
                  for k in ('report_2024', 'report_2025')
                  if any(s in ((c.get(k) or {}).get('url') or '')
                         for s in ('m12333', 'si12333', '51shebao', 'sohu.com'))})
    print()
    print('全库残留聚合站/门户链接城市（下一批清理候选，%d 个）：%s' % (len(agg), '、'.join(agg)))
    return 0 if not miss else 1


if __name__ == '__main__':
    sys.exit(main())
