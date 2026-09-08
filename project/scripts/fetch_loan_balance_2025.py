# -*- coding: utf-8 -*-
"""
批量抓取 + 解析 135 城 2025 年度公积金年报的「个人住房贷款余额」与同比。

口径（2026-09-08 与用户对齐）：
  - 贷款余额 = 年报原文「个人住房贷款余额」（北京例：贷款余额5023.40亿元，下降1.7%）
  - 同比：原文披露优先（含「分别比上年末增长a%、b%、下降c%」取最后一个）；
    原文未披露同比的，标记 need_2024=True，后续用 2024 年报余额自行计算
  - 失败/未披露的城市 value 置 null 并记 reason，生成待办清单

流程：
  1. httpget 直连抓 report_2025.url；
  2. 文本落盘 project/data/loan_balance_2025_txt/<城市>.txt 便于人工核对；
  3. 结果写入 project/data/loan_balance_2025_result.json；
  4. 失败清单写入 project/data/loan_balance_2025_failed.json。
"""
import sys
import os
import re
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import httpget

ROOT = os.path.dirname(HERE)          # .../gjj-policy-watch/project
REPO = os.path.dirname(ROOT)          # .../gjj-policy-watch
DB = os.path.join(REPO, 'gjj_policy_database.json')
OUTDIR = os.path.join(ROOT, 'data', 'loan_balance_2025_txt')
OUTJSON = os.path.join(ROOT, 'data', 'loan_balance_2025_result.json')
FAILJSON = os.path.join(ROOT, 'data', 'loan_balance_2025_failed.json')

HEADERS = {
    'User-Agent': httpget.UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'close',
}

# 文本有效性关键词：年报正文必含
PAGE_KEYWORDS = ('贷款', '住房公积')
HIT_KEYWORD = '贷款余额'


def html2text(html):
    try:
        from cdp_fetch import html2text as _h
        return _h(html)
    except Exception:
        html = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', html)
        html = re.sub(r'(?s)<[^>]+>', ' ', html)
        html = re.sub(r'&nbsp;?', ' ', html)
        html = re.sub(r'&[a-z]+;', ' ', html)
        return re.sub(r'\s+', ' ', html)


def normalize(t):
    t = t.replace('％', '%').replace('亿 元', '亿元')
    t = t.replace(',', ',').replace(',', ',')
    return re.sub(r'[ \t\u3000]+', '', t)


UP_VERBS = ('增加', '增长', '上升', '提高')
DOWN_VERBS = ('下降', '降低', '减少', '回落')


def parse_balance(text, issued_2025=None):
    """从年报纯文本中提取 (余额亿元, yoy字符串或None, 原文片段)。

    规则：
      1. 优先取「个人住房贷款余额」，其次取「个贷余额」，最后取贷款段落里的「贷款余额」；
         兼容脚注标记（贷款余额[4]2,561.75亿元 / 贷款余额①…）；
      2. 同比：同一句内先找「分别比上年末…」取最后一个百分比（兼容「增加-1.53%」负号
         与「比上年同期末」写法）；再找单值句式；找不到 → need_2024；
      3. 双中心（市中心+区直/铁路分中心）分列披露 → 合并求和，同比置 need_2024；
      4. 无多中心标记但出现多个不同余额 → 视为歧义，返回 suspect；
      5. 余额/当年发放额比值 <1.5 或 >40（发放额>5亿时）→ 视为可疑（省级数据混入）。
    """
    t = normalize(text)
    # 锚点分层：优先「个人住房贷款余额」，无匹配再退「个贷余额」「贷款余额」
    matches = []
    for pat in (r'个人住房贷款余额', r'个贷余额', r'贷款余额'):
        for m in re.finditer(pat, t):
            sent = t[max(0, m.start() - 200):min(len(t), m.start() + 280)]
            # 排除「异地贷款余额」「公转商贴息贷款余额」
            pre = sent[:sent.rfind(pat[:2]) if pat[:2] in sent else len(sent)]
            seg = sent[:sent.find('贷款余额') if '贷款余额' in sent else len(sent)]
            if '异地' in seg or '公转商' in seg:
                continue
            mb = re.search(r'贷款余额(?:\[\d+\]|[①②③④⑤⑥⑦⑧⑨⑩])?\s*([0-9][0-9,，.]*)亿元', sent)
            if not mb:
                continue
            raw = mb.group(1).replace(',', '').replace('，', '')
            try:
                value = round(float(raw), 2)
            except ValueError:
                continue
            if value < 5 or value > 100000:
                continue
            # 严格切句：只在本句（。；分隔）内找同比，防止串句误抓
            end = len(sent)
            for ch in ('。', '；', '！', '？', '\n'):
                i = sent.find(ch, mb.end())
                if i != -1:
                    end = min(end, i)
            last_dot = sent.rfind('。', 0, mb.start())
            cstart = last_dot + 1 if last_dot != -1 else 0
            core = sent[cstart:end]
            yoy = None
            VERB = '|'.join(UP_VERBS + DOWN_VERBS)
            # 百分比（排除「X个百分点」这类非同比用法）
            PCT = r'(-?[0-9]+(?:\.[0-9]+)?)\s*%(?!\s*个?百分)'

            # A 级（最高优先）：余额数字之后紧跟的显式同比句「(，)同比/比上年末…增长|下降 X%」。
            # 约束：① 前缀 ≤14 字符且不含「分别」——含「分别」说明它属于前面发放额共用电头的
            #       并列组，不是余额自己的同比（南通：「累计发放…分别增加2.69%、5.64%，
            #       贷款余额488.78亿元，比上年末减少2.13%」）；
            #      ② 前缀不含「占」，避免误吃「占缴存余额的70.46%」；③ 排除「X个百分点」。
            tail_after = core[max(0, mb.end() - cstart):]
            CMP = r'(?:同比|(?:比|较)(?:上年|去年)(?:同期)?末?)'
            # 中间缓冲组：同样禁止出现「分别」——倒装句式「比上年末分别增加3.75%、5.35%、减少1.93%」
            # 的「分别」落在比较词之后，不挡住会误取首项（惠州/榆林曾因此取错）。
            MID = r'((?:(?!分别)[^。；%]){0,10}?)'
            # A2：余额数字后「紧邻」的同比句（re.match 锚定开头，前缀 ≤6 字符）。
            #     南通/温州/襄阳式：「贷款余额488.78亿元，比上年末减少2.13%」。
            mA = re.match(
                r'((?:(?!分别|占)[^。；]){0,6}?)' + CMP + MID +
                r'(' + VERB + r')' + PCT, tail_after)
            if mA is None:
                # A1：句内以「贷款余额」为显式主语的同比句（前缀 ≤14 字符且不含「分别」）。
                #     衢州/镇江式：「贷款余额159.43亿元，…分别增加2.66%、5.67%，
                #                  贷款余额比上年末下降0.86%」。
                mA = re.search(
                    r'贷款余额((?:(?!分别|占)[^。；]){0,14}?)' + CMP + MID +
                    r'(' + VERB + r')' + PCT, tail_after)
            # 注：北京式「贷款余额5023.40亿元，分别比上年末增长3.9%、6.1%、下降1.7%」
            #     两种形式都会被「分别」挡住，正确落到下面 B 级的共用电头分支取末位 -1.7%。
            if mA:
                d, p = mA.group(3), mA.group(4)
                down = d in DOWN_VERBS or p.startswith('-')
                yoy = ('-' if down else '+') + p.lstrip('-') + '%'

            if yoy is None:
                m_sep = (re.search(r'分别(?:(?:比|较)(?:上年|去年)(?:同期)?末?|同比)', core)
                         or re.search(r'(?:比|较)(?:上年|去年)(?:同期)?末?分别', core))
                if m_sep:
                    # 「分别比上年末增长3.9%、6.1%、下降1.7%」/「增加6.71%、9.87%、2.6%」共用电头。
                    # 只吃「分别」之后由顿号连接的连续百分比序列末位，避免吃掉后面
                    # 「，个人住房贷款余额占缴存余额的70.46%」这类无关百分比（日照曾因此误抓）。
                    tail = core[m_sep.start():]
                    m0 = re.search(r'(' + VERB + r')?\s*' + PCT, tail)
                    if m0:
                        d, p = m0.group(1), m0.group(2)
                        pos = m0.end()
                        while True:
                            # 分隔符含「和」：呼伦贝尔「增加2.79%、5.05%和减少3.49%」
                            m1 = re.match(r'\s*(?:、|和)\s*(' + VERB + r')?\s*' + PCT, tail[pos:])
                            if not m1:
                                break
                            d, p = m1.group(1), m1.group(2)
                            pos += m1.end()
                        down = (d in DOWN_VERBS) if d else p.startswith('-')
                        yoy = ('-' if down else '+') + p.lstrip('-') + '%'

            if yoy is None:
                # 单值句式：「同比下降3.56%」「比上年末增长X%」
                m_single = re.search(
                    r'(?:同比|(?:比|较)(?:上年|去年)(?:同期)?末?)([^。；%,]{0,12}?)(' + VERB + r')' + PCT,
                    core)
                if m_single:
                    d, p = m_single.group(2), m_single.group(3)
                    down = d in DOWN_VERBS or p.startswith('-')
                    yoy = ('-' if down else '+') + p.lstrip('-') + '%'
            matches.append({'value': value, 'yoy': yoy, 'snippet': sent[:300]})
        if matches:
            break
    if not matches:
        return None

    multi_center = any(k in t for k in ('区直分中心', '区直中心', '铁路分中心', '铁路局分中心', '区分中心'))
    values = sorted({m['value'] for m in matches})
    if len(values) == 1:
        pick = matches[0]
    elif multi_center:
        pick = {'value': round(sum(values), 2), 'yoy': None,
                'snippet': '；'.join(m['snippet'][:120] for m in matches)}
    else:
        # 年报结构：全市总述在前、分中心明细在后 → 取首个
        pick = matches[0]

    # 合理性：余额 / 当年发放额
    if issued_2025 and issued_2025 > 5:
        ratio = pick['value'] / issued_2025
        if ratio < 1.5 or ratio > 40:
            pick['suspect'] = f'ratio_{ratio:.1f}'
    pick['need_2024'] = pick.get('yoy') is None
    return pick


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--city', nargs='*', default=None)
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    db = json.load(open(DB, encoding='utf-8'))
    cities = db['annual_reports']['cities']
    if args.city:
        cities = [c for c in cities if c['city'] in args.city]

    os.makedirs(OUTDIR, exist_ok=True)
    results, failed = {}, []

    for c in cities:
        city = c['city']
        rpt = c.get('report_2025') or {}
        url = rpt.get('url')
        title = rpt.get('title') or ''
        entry = {'value': None, 'yoy': None, 'need_2024': False,
                 'url': url, 'snippet': None, 'status': None}
        # 已知市级年报缺口（省级来源，数值不可挂城市）→ 直接待办
        if '未检索到' in title:
            entry['status'] = 'provincial_known_gap'
            failed.append({'city': city, **entry})
            results[city] = entry
            print(f'== {city} == 跳过（市级年报已知缺口，省级来源）')
            continue
        issued_2025 = ((c.get('stats_2025') or {}).get('loan_issued') or {}).get('value')
        cache = os.path.join(OUTDIR, f'{city}.txt')
        if os.path.exists(cache) and os.path.getsize(cache) > 500:
            txt = open(cache, encoding='utf-8').read()
            status = 200
        else:
            try:
                r = httpget.get(url, timeout=30, headers=HEADERS)
            except Exception as ex:
                r = {'status': 0, 'text': '', 'error': f'{type(ex).__name__}: {ex}'}
            status = r.get('status')
            txt = html2text(r.get('text') or '') if status == 200 else ''
        ok_page = txt and all(k in txt for k in PAGE_KEYWORDS)
        parsed = parse_balance(txt, issued_2025) if ok_page else None
        if parsed and not parsed.get('suspect'):
            entry.update({'value': parsed['value'], 'yoy': parsed['yoy'],
                          'need_2024': parsed['need_2024'],
                          'snippet': parsed['snippet'], 'status': 'ok'})
            open(cache, 'w', encoding='utf-8').write(txt)
            print(f'== {city} == 余额={parsed["value"]} yoy={parsed["yoy"]}'
                  f'{" [缺同比]" if parsed["need_2024"] else ""}')
        elif parsed:  # suspect
            entry['status'] = f'suspect:{parsed["suspect"]}'
            entry['snippet'] = (parsed['candidates'][0]['snippet'] if 'candidates' in parsed
                                else parsed.get('snippet'))
            failed.append({'city': city, **entry})
            print(f'== {city} == [{entry["status"]}] 可疑值，转人工')
        else:
            entry['status'] = status
            entry['error'] = (r.get('error') if status != 200 else None) or \
                             ('no_keyword' if (txt and not ok_page) else 'empty')
            failed.append({'city': city, **entry})
            print(f'== {city} == [{entry["status"]}] FAIL {entry.get("error", "")} {(url or "")[:70]}')
        results[city] = entry

    json.dump(results, open(OUTJSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    json.dump(failed, open(FAILJSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    ok = sum(1 for v in results.values() if v['value'] is not None)
    need24 = sum(1 for v in results.values() if v['value'] is not None and v['need_2024'])
    print(f'\n成功 {ok}/{len(results)}；其中缺同比需补 2024 余额 {need24} 个；抓取失败 {len(failed)} 个')
    print(f'结果 → {OUTJSON}\n失败 → {FAILJSON}')


if __name__ == '__main__':
    main()
