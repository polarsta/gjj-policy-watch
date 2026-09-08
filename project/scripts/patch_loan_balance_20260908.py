# -*- coding: utf-8 -*-
"""
把 2025 年贷款余额 + 同比 写入 gjj_policy_database.json。

口径（2026-09-08 与用户对齐）：
  - stats_2025.loan_balance = {value, unit, yoy, source_url, source_name, extract_method[, note]}
  - 同比：年报原文披露优先；未披露的用 2024 年报余额自行计算（extract_method 注明）
  - 抓取失败/省级来源/无链接的城市 value 置 null，note 记录原因（待办）
  - 版本号 1.5.5 → 1.5.6（main 同为 1.5.5，须递进避撞车）

写库遵循项目规范：detect_indent 取全文件最小正缩进（主库=1 空格）、
保留原始 EOF 状态（本文件末尾无换行）、dry-run 默认、--apply 落盘。
"""
import sys
import os
import re
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)
DB = os.path.join(REPO, 'gjj_policy_database.json')
RES = os.path.join(ROOT, 'data', 'loan_balance_2025_result.json')

NEW_VERSION = '1.5.6'

# ---- 人工核定/特殊来源 ----
SPECIAL = {
    '成都': {'source_url': 'http://www.chinajsb.cn/html/202603/30/55798.html',
             'source_name': '成都住房公积金2025年年度报告（中国建设新闻网转载全文）',
             'extract_method': '年报正文（CDP渲染）'},
    '哈尔滨': {'source_url': 'https://www.hrbgjj.org.cn/ndbg/2416.jhtml',
               'source_name': '哈尔滨市住房公积金2025年年度报告（中心官网）',
               'extract_method': '年报正文',
               'fill_report_2025': {'title': '哈尔滨市住房公积金2025年年度报告',
                                    'url': 'https://www.hrbgjj.org.cn/ndbg/2416.jhtml'}},
    '台州': {'fill_report_2025': {'title': '台州市住房公积金2025年年度报告',
                                  'url': 'https://gjj.zjtz.gov.cn/col/col1229045868/art/2026/art_7320f83eabe849af8d05ae05a02f8fe1.html'}},
    # 合肥：值取省住建厅官方分城市表；原文披露同比+7.69%（官方微信，可点击链接待补）
    '合肥': {'source_url': 'https://dohurd.ah.gov.cn/wjgk/tzgg/58221441.html',
             'source_name': '安徽省住房公积金2025年年度报告（分城市表）',
             'extract_method': '省级年报分城市表',
             'value': 832.47,
             'yoy': None,
             'note': '市级年报原文披露同比+7.69%（分别比上年末增加5.48%、10.68%、7.69%），发布于合肥公积金官方微信，可点击链接待补'},
    '南宁': {'yoy': '-0.98%', 'extract_method': '由2024年余额计算',
             'note': '市中心+区直分中心合并口径；同比按2024年末余额540.24亿元（2024年报同口径合计）计算，原文分别披露市中心-3.71%'},
    '大连': {'yoy': '+1.41%', 'extract_method': '由2024年余额计算',
             'note': '年报原文未披露余额同比；按2024年末余额736.00亿元（2024年报）计算'},
}

# 无值城市的分类说明（写入 note，作为待办）
NULL_NOTES = {
    '海口': '海南省为全省统一法人（无独立设置的分支机构），不发布市级年报；本条数据由「海南省」条目覆盖',
    '三亚': '海南省为全省统一法人（无独立设置的分支机构），不发布市级年报；本条数据由「海南省」条目覆盖',
    '黄冈': '市级2025年报全文未检索到，现有来源为湖北省级汇总，无法拆出市级余额（待办）',
    '孝感': '市级2025年报全文未检索到，现有来源为湖北省级汇总（待办）',
    '荆州': '市级2025年报全文未检索到，现有来源为湖北省级汇总（待办）',
    '娄底': '市级2025年报全文未检索到，现有来源为湖南省级汇总（待办）',
    '洛阳': '现有来源为河南省2025年年度报告，市级余额待从洛阳中心官方渠道补充（待办）',
    '红河': '市级年报全文未检索到，取自云南省年报分城市表，其中无贷款余额列（待办）',
    '株洲': '现有链接为湖南省住建厅省级页面，抓取值为全省数据已剔除（待办）',
    '包头': '现有页面抓取值为内蒙古区级数据（余额1318.90亿元）已剔除，市级余额待补（待办）',
    '大庆': '现有来源为黑龙江省2025年年度报告（PDF 防盗链无法下载），市级余额待补（待办）',
    '重庆': '中心官网 cqgjj.cn DNS 解析失败，年报全文待人工获取（待办）',
    '兰州': '现有来源为媒体转载页且正文加载不全，待补官方原文（待办）',
    '廊坊': '中心官网为 JS 渲染且反爬拦截，直连/无头浏览器均未取到正文（待办）',
    '丽江': '现有来源为搜狐转载且正文为图片，待补官方原文（待办）',
    '日照': '现有来源为媒体「数说」页且正文为图片，待补官方原文（待办）',
    '清远': '政府站 WAF 412 拦截，待人工获取（待办）',
    '衡阳': '政府站 WAF 412 拦截，待人工获取（待办）',
}


def detect_indent(raw):
    """取全文件最小正缩进（列数）。"""
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

    res = json.load(open(RES, encoding='utf-8'))
    cities = db['annual_reports']['cities']
    n_ok = n_null = 0
    for c in cities:
        city = c['city']
        r = res.get(city) or {}
        sp0 = SPECIAL.get(city, {})
        rpt = c.setdefault('report_2025', {}) or {}
        if r.get('value') is not None or sp0.get('value') is not None:
            sp = sp0
            value = sp.get('value', r['value'])
            yoy = sp.get('yoy', r.get('yoy'))
            entry = {'value': value, 'unit': '亿元', 'yoy': yoy,
                     'source_url': sp.get('source_url', (c.get('report_2025') or {}).get('url')),
                     'source_name': sp.get('source_name', rpt.get('title') or ''),
                     'extract_method': sp.get('extract_method', '年报正文')}
            if sp.get('note'):
                entry['note'] = sp['note']
            if yoy is None and 'note' not in entry:
                entry['note'] = '年报原文未披露余额同比，待补（可按2024年报余额计算）'
            c.setdefault('stats_2025', {})['loan_balance'] = entry
            if sp.get('fill_report_2025'):
                rpt.update(sp['fill_report_2025'])
            n_ok += 1
        else:
            note = NULL_NOTES.get(city, '抓取失败，待人工核补（待办）')
            c.setdefault('stats_2025', {})['loan_balance'] = {
                'value': None, 'unit': '亿元', 'yoy': None, 'note': note}
            n_null += 1

    # 字段单位与口径说明
    fu = db['annual_reports'].get('field_units')
    if isinstance(fu, dict):
        fu['loan_balance'] = '亿元'
    db['annual_reports']['yoy_note'] = (
        '提取额 / 发放贷款的「同比±X%」与「▲增加 / ▼减少 X 亿元」均以 stats_2025 与 stats_2024 的绝对值口径自行计算，'
        '非年报原文直接披露值；贷款余额(loan_balance)的 value 与 yoy 优先取 2025 年年报原文披露值'
        '（「分别比上年末增长a%、b%、c%」取末位对应余额），仅南宁/大连因原文未披露改按 2024 年报余额计算')
    db['version'] = NEW_VERSION

    out = json.dumps(db, ensure_ascii=False, indent=indent)
    if not eof_newline:
        out = out.rstrip('\n')

    if args.apply:
        open(DB, 'w', encoding='utf-8').write(out)
        print(f'已写入 {DB}（indent={indent}, eof_newline={eof_newline}）')
    else:
        import difflib
        old_lines = raw.split('\n')
        new_lines = out.split('\n')
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm='', n=1))
        print(f'dry-run: {len(diff)} 行 diff，有值 {n_ok}，置空 {n_null}，version→{NEW_VERSION}')
        for line in diff[:60]:
            print(line[:160])


if __name__ == '__main__':
    main()
