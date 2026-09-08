# -*- coding: utf-8 -*-
"""
2025 年报贷款余额 + 同比 —— 第二轮补丁（2026-09-08 与用户清单核对后）。

变更要点：
  1. 用用户 2026-09-08 提供的核定清单补齐自动抓取失败的城市（USER_FILL）；
  2. 南宁按用户口径改为「市中心」323.04 亿元 / -3.71%（区直分中心另计，写入 note）；
  3. 大连按用户口径 yoy 置 null（年报未体现），自算值 +1.41% 保留在 note 供参考；
  4. 衢州/镇江维持年报原文口径（清单取的是「累计发放金额」同比，非贷款余额同比）；
  5. 版本号 1.5.6 → 1.5.7。

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

NEW_VERSION = '1.5.7'

# ---- 用户核定清单兜底（自动抓取失败的城市；source_url 一律挂官方年报地址）----
USER_FILL = {
    '合肥': (832.47, '+7.69%',
             '中心官网页面返回 521 未能直连核验；余额 832.47 亿元取自安徽省住建厅 2025 年度报告分城市表，'
             '同比 +7.69% 为年报原文披露值（分别比上年末增加 5.48%、10.68%、7.69%）'),
    '黄冈': (120.81, '-4.03%', '中心官网为框架页，正文未能直连取到；数据取自用户核定清单（黄冈中心官网年报）'),
    '荆州': (111.65, '-1.93%', '中心官网为框架页，正文未能直连取到；数据取自用户核定清单（荆州中心官网年报）'),
    '衡阳': (116.86, '-5.22%', '政府站 WAF 412 拦截，未能直连取到正文；数据取自用户核定清单'),
    '重庆': (2153.99, '+6.44%', '中心官网 cqgjj.cn 域名解析失败，年报全文未能直连获取；数据取自用户核定清单'),
    '清远': (100.80, '-5.26%', '政府站 WAF 412 拦截，未能直连取到正文；数据取自用户核定清单'),
    '洛阳': (2964.23, '-0.26%',
             '⚠️ 该值与河南省 2025 年度报告全省口径一致，疑为省级数据而非洛阳市级；'
             '市级年报未检索到，待从洛阳中心官方渠道核实'),
    '丽江': (46.35, '+4.84%', '现有来源为转载页且正文为图片，未能直连取到；数据取自用户核定清单'),
    '红河': (117.63, '+0.92%', '市级年报未检索到，取自云南省年报分城市表；数据取自用户核定清单'),
    '包头': (174.19, '-3.86%',
             '此前自动抓取到的 1318.90 亿元为内蒙古区级数据已剔除；数据取自用户核定清单'),
    '大庆': (187.72, None, '年报原文未披露余额同比；余额取自用户核定清单'),
    '廊坊': (148.96, '+1.58%', '中心官网为 JS 渲染且反爬拦截，直连/无头浏览器均未取到正文；数据取自用户核定清单'),
}

# ---- 人工口径修正 ----
SPECIAL = {
    # 南宁：按用户口径取「南宁住房公积金管理中心（含铁路分中心）」323.04 亿元
    '南宁': {'value': 323.04, 'yoy': '-3.71%', 'extract_method': '年报正文',
             'note': '市中心（含铁路分中心）口径；另有区直分中心贷款余额 211.91 亿元（+3.49%），'
                     '两个中心合计 534.95 亿元'},
    # 大连：年报未披露同比，按用户口径置 null，自算值供参考
    '大连': {'yoy': None, 'extract_method': '年报正文',
             'note': '年报原文未披露贷款余额同比（按 2024 年末余额 736.00 亿元测算约 +1.41%，仅供参考）'},
    # 衢州/镇江：清单中的百分比为「累计发放金额」同比，贷款余额同比以年报原文为准
    '衢州': {'note': '年报原文：贷款余额 159.43 亿元，比上年末下降 0.86%'
                     '（句中「分别增加 2.66%、5.67%」为累计发放笔数与金额的同比，非余额同比）'},
    '镇江': {'note': '年报原文：贷款余额 156.30 亿元，同比下降 6.8%'
                     '（句中「分别增加 2.14%、3.85%」为累计发放笔数与金额的同比，非余额同比）'},
    '成都': {'source_url': 'http://www.chinajsb.cn/html/202603/30/55798.html',
             'source_name': '成都住房公积金2025年年度报告（中国建设新闻网转载全文）',
             'extract_method': '年报正文（CDP渲染）'},
}

# 仍无值城市的说明（海口/三亚）
NULL_NOTES = {
    '海口': '海南省为全省统一法人（无独立设置的分支机构），不发布市级年报；本条数据由「海南省」条目覆盖',
    '三亚': '海南省为全省统一法人（无独立设置的分支机构），不发布市级年报；本条数据由「海南省」条目覆盖',
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
    ap.add_argument('--result', default=os.path.join(
        os.path.dirname(HERE), 'data', 'loan_balance_2025_result.json'))
    args = ap.parse_args()

    raw = open(DB, encoding='utf-8').read()
    indent = detect_indent(raw)
    eof_newline = raw.endswith('\n')
    db = json.loads(raw)

    res = json.load(open(args.result, encoding='utf-8'))
    cities = db['annual_reports']['cities']
    n_ok = n_null = n_fill = 0

    for c in cities:
        city = c['city']
        r = res.get(city) or {}
        sp = SPECIAL.get(city, {})
        rpt = c.setdefault('report_2025', {}) or {}
        fill = USER_FILL.get(city)

        if r.get('value') is not None:
            value = sp.get('value', r['value'])
            yoy = sp.get('yoy', r.get('yoy'))
            entry = {'value': value, 'unit': '亿元', 'yoy': yoy,
                     'source_url': sp.get('source_url', rpt.get('url')),
                     'source_name': sp.get('source_name', rpt.get('title') or ''),
                     'extract_method': sp.get('extract_method', '年报正文')}
        elif fill:
            value, yoy, note = fill
            entry = {'value': value, 'unit': '亿元', 'yoy': yoy,
                     'source_url': rpt.get('url'),
                     'source_name': rpt.get('title') or '',
                     'extract_method': '用户核定清单（2026-09-08）',
                     'note': note}
            n_fill += 1
        else:
            entry = {'value': None, 'unit': '亿元', 'yoy': None,
                     'note': NULL_NOTES.get(city, '年报全文未获取到，待人工核补（待办）')}
            n_null += 1

        if sp.get('note'):
            entry['note'] = sp['note']
        if entry.get('value') is not None and entry.get('yoy') is None and 'note' not in entry:
            entry['note'] = '年报原文未披露余额同比，待补（可按2024年报余额计算）'

        c.setdefault('stats_2025', {})['loan_balance'] = entry
        if entry['value'] is not None:
            n_ok += 1

    fu = db['annual_reports'].get('field_units')
    if isinstance(fu, dict):
        fu['loan_balance'] = '亿元'
    db['annual_reports']['yoy_note'] = (
        '提取额 / 发放贷款的「同比±X%」与「▲增加 / ▼减少 X 亿元」均以 stats_2025 与 stats_2024 的绝对值口径自行计算，'
        '非年报原文直接披露值；贷款余额(loan_balance)的 value 与 yoy 优先取 2025 年年报原文披露值'
        '（「分别比上年末增长a%、b%、c%」取末位对应余额）；抓取失败城市由用户核定清单补齐并在 note 注明')
    db['version'] = NEW_VERSION

    out = json.dumps(db, ensure_ascii=False, indent=indent)
    if not eof_newline:
        out = out.rstrip('\n')

    print(f'有值 {n_ok}（其中用户清单补齐 {n_fill}）｜置空 {n_null}｜version→{NEW_VERSION}｜indent={indent}')

    if args.apply:
        open(DB, 'w', encoding='utf-8').write(out)
        print(f'已写入 {DB}（eof_newline={eof_newline}）')
    else:
        diff = list(difflib.unified_diff(raw.split('\n'), out.split('\n'), lineterm='', n=0))
        print(f'dry-run: {len(diff)} 行 diff')
        for line in diff[:40]:
            print(line[:170])


if __name__ == '__main__':
    main()
