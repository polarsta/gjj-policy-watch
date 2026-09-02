# -*- coding: utf-8 -*-
"""
批量抓取各市《住房公积金 2024 年年度报告》原文，抽取 2024 年
  - 提取额（亿元）
  - 发放个人住房贷款额（亿元）
用于与 2025 年报数值计算同比增幅与增减量。

产物：
  project/data/annual_raw/{city}_2024.html   原文快照（便于复核/重解析）
  project/data/annual_2024_candidates.json   候选值 + 上下文（供人工核验）
只做抓取与候选抽取，不写回主库；回填由 patch 脚本完成。
"""
import json
import os
import re
import ssl
import gzip
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, 'gjj_policy_database.json')
RAW_DIR = os.path.join(ROOT, 'project', 'data', 'annual_raw')
OUT = os.path.join(ROOT, 'project', 'data', 'annual_2024_candidates.json')

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
REPARSE = False


def fetch(url, timeout=30, retry=2):
    last = None
    for i in range(retry + 1):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA,
                'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Connection': 'close',
            })
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                body = r.read()
                if r.headers.get('Content-Encoding') == 'gzip':
                    body = gzip.decompress(body)
            enc = 'utf-8'
            m = re.search(rb'charset=["\']?\s*([\w-]+)', body[:3000], re.I)
            if m:
                e = m.group(1).decode('ascii', 'ignore').lower()
                if e in ('gb2312', 'gbk', 'gb18030'):
                    enc = 'gb18030'
                elif e in ('utf-8', 'utf8'):
                    enc = 'utf-8'
            return body.decode(enc, 'ignore')
        except Exception as ex:
            last = f'{type(ex).__name__}: {ex}'
            time.sleep(1.2 * (i + 1))
    return {'__error__': last}


def html2text(html):
    t = re.sub(r'(?is)<script.*?</script>|<style.*?</style>|<!--.*?-->', ' ', html)
    t = re.sub(r'(?i)</(p|div|tr|td|th|br|li|h\d)>', '\n', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r'&nbsp;|&#160;|&emsp;', ' ', t)
    t = re.sub(r'&amp;', '&', t)
    t = re.sub(r'[ \t\u3000]+', ' ', t)
    t = re.sub(r'\n\s*\n+', '\n', t)
    return t.strip()


NUM = r'([\d,]+(?:\.\d+)?)'

# 提取额：按可信度从高到低；w2/w3 覆盖「提取金额」等异形口径（如盘锦）
PAT_WITHDRAW = [
    ('w1', re.compile(rf'提取额\s*(?:为|达|共计|合计|是)?\s*[：:]?\s*{NUM}\s*亿元')),
    ('w2', re.compile(rf'提取金额\s*(?:为|达|共)?\s*[：:]?\s*{NUM}\s*亿元')),
    ('w3', re.compile(rf'(?:全年|当年)?提取(?:住房)?公积金\s*(?:共计|合计|总额|金额)?\s*[：:]?\s*{NUM}\s*亿元')),
    ('w4', re.compile(rf'提取额\s*(?:为|达|是)?\s*[：:]?\s*{NUM}\s*万元')),
    ('w5', re.compile(rf'住房?公积金提取(?:额|金额|资金)\s*(?:为|达)?\s*[：:]?\s*{NUM}\s*亿元')),
    ('w6', re.compile(rf'(?<!租房)(?<!租赁)提取\s*{NUM}\s*亿元')),
]
# 子类口径（租房/住房消费/购房提取等）：绝不可当作全市提取额
SUB_WITHDRAW = re.compile(r'租房提取|租赁提取|住房消费类提取|非住房消费类提取|购房提取|还贷提取|离退休提取|大修提取')
# 发放贷款（笔数可写作 0.70万笔 / 1.87万笔 / 36笔）
PAT_LOAN = [
    ('l1', re.compile(rf'发放(?:住房公积金)?个人住房贷款\s*{NUM}\s*万?笔\s*[、，,]?\s*{NUM}\s*亿元')),
    ('l2', re.compile(rf'发放(?:住房公积金)?个人住房贷款\s*{NUM}\s*亿元')),
    ('l3', re.compile(rf'发放(?:住房公积金)?个人住房贷款\s*[^\n。；]{{0,12}}?{NUM}\s*万元')),
    ('l4', re.compile(rf'发放(?:个人)?住房贷款\s*{NUM}\s*亿?元')),
    ('l5', re.compile(rf'发放贷款\s*{NUM}\s*亿元')),
    ('l6', re.compile(rf'贷款发放额\s*(?:为|达)?\s*[：:]?\s*{NUM}\s*亿元')),
    ('l7', re.compile(rf'发放(?:住房公积金)?贷款\s*{NUM}\s*亿元')),
]
# 排除词只作用于「匹配点紧邻窗口」，避免误杀同句前后的累计口径数据
BAD_NEAR = re.compile(r'(?:累计|历年|总额|余额|公转商|贴息贷款|项目贷款|回收|转出|异地贷款)')
NEAR_BEFORE, NEAR_AFTER = 26, 8


def to_num(s):
    try:
        return float(str(s).replace(',', ''))
    except Exception:
        return None


# 章节定位：全市合计口径必定写在「（二）提取 /（三）贷款」段落内、且早于「其中：」分中心拆解
SEC_PAT = {
    'withdraw': (r'[（(]\s*二\s*[）)]\s*提取(?:业务)?|[^）)]\n\s*提取\s*[:：]',
                 r'[（(]\s*三\s*[）)]|其中\s*[:：]|其中，|分中心'),
    'loan': (r'[（(]\s*三\s*[）)]\s*贷(?:款|款业务)|[^）)]\n\s*贷\s*款\s*[:：]',
             r'[（(]\s*四\s*[）)]|其中\s*[:：]|其中，|分中心'),
}


def section_span(text, kind):
    """返回 (start, end) 章节窗口；定位不到则回退全文"""
    s_pat, e_pat = SEC_PAT[kind]
    m = re.search(s_pat, text)
    if not m:
        return 0, len(text)
    start = m.start()
    tail = text[start + len(m.group(0)):start + 1500]
    me = re.search(e_pat, tail)
    end = start + len(m.group(0)) + (me.start() if me else 1500)
    return start, min(end, len(text))


def pick(text, pats, kind=None, unit_default='亿元', span=90, sub_bad=None):
    """返回 [{'pat','value','unit','ctx'}]：章节内匹配优先，其次按文档位置，最后按模式优先级"""
    out = []
    s_sec, e_sec = section_span(text, kind) if kind else (0, len(text))
    for pid, p in pats:
        for m in p.finditer(text):
            raw = m.groups()[-1]
            v = to_num(raw)
            if v is None:
                continue
            seg = m.group(0)
            if '万元' in seg:
                unit, val = '万元', round(v / 10000, 4)
            elif '亿元' in seg:
                unit, val = '亿元', v
            else:
                unit, val = unit_default, v
            # 紧邻窗口排除：匹配点前 26 字 / 后 8 字出现累计类字样则判为不可比口径
            near = text[max(0, m.start() - NEAR_BEFORE):m.start()] + seg[:NEAR_AFTER + 6]
            if BAD_NEAR.search(near):
                continue
            if sub_bad and sub_bad.search(text[max(0, m.start() - 18):m.start() + 6]):
                continue
            s = max(0, m.start() - span)
            e = min(len(text), m.end() + span)
            ctx = re.sub(r'\s+', ' ', text[s:e])
            out.append({'pat': pid, 'value': val, 'unit': '亿元', 'raw': seg, 'ctx': ctx,
                        'pos': m.start(), 'in_sec': s_sec <= m.start() < e_sec})
    seen, uniq = set(), []
    # 章节内 > 文档靠前 > 模式优先级
    for o in sorted(out, key=lambda x: (not x['in_sec'], x['pos'], x['pat'])):
        k = (o['pat'], o['value'])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(o)
    return uniq[:6]


def norm_city(s):
    """城市名归一化：去掉 市/地区/自治州/州/区/县 等后缀后比对（吉林/吉林市历史命名坑）"""
    return re.sub(r'(市|地区|自治州|盟|州|区|县)$', '', str(s).strip())


def parse_city_table(html, city, col_keywords):
    """
    省级年报（如河南省、湖北省）正文给的是全省数，市级数据只在「分城市」表格里。
    定位表头含 col_keywords 的列，再按城市名取该行数值。
    """
    target = norm_city(city)
    for tb in re.findall(r'(?is)<table.*?</table>', html):
        grid = []
        for r in re.findall(r'(?is)<tr.*?</tr>', tb):
            cells = re.findall(r'(?is)<t[dh][^>]*>(.*?)</t[dh]>', r)
            cells = [re.sub(r'<[^>]+>', '', c).replace('&nbsp;', ' ').strip() for c in cells]
            if cells:
                grid.append(cells)
        if len(grid) < 2:
            continue
        for i, row in enumerate(grid):
            hit = [j for j, c in enumerate(row) if any(k in c for k in col_keywords)]
            if not hit:
                continue
            col = hit[0]
            for rr in grid[i + 1:]:
                if not rr or norm_city(rr[0]) != target or len(rr) <= col:
                    continue
                v = to_num(rr[col])
                if v is not None and v > 0:
                    return {'pat': 'table', 'value': v, 'unit': '亿元',
                            'raw': ' | '.join(rr[:6]), 'ctx': '表头: ' + ' | '.join(row[:6])}
    return None


def work(item):
    city, url = item
    res = {'city': city, 'url': url, 'ok': False}
    if not url:
        res['err'] = 'NO_URL'
        return res
    path = os.path.join(RAW_DIR, f'{city}_2024.html')
    html = None
    if os.path.exists(path) and os.path.getsize(path) > 500:
        with open(path, encoding='utf-8', errors='ignore') as f:
            html = f.read()
    elif REPARSE:
        res['err'] = 'NO_SNAPSHOT'
        return res
    if html is None:
        html = fetch(url)
        if isinstance(html, dict):
            res['err'] = html['__error__']
            return res
        os.makedirs(RAW_DIR, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
    res['ok'] = True
    res['len'] = len(html)
    txt = html2text(html)
    # 省级年报：正文为全省数，市级数据须取分城市表格
    is_prov = bool(re.search(r'全省|分市州|分城市|各市（州）|各市\(州\)', txt))
    res['province_level'] = is_prov
    res['withdraw'] = pick(txt, PAT_WITHDRAW, kind='withdraw', sub_bad=SUB_WITHDRAW)
    res['loan'] = pick(txt, PAT_LOAN, kind='loan')
    if is_prov:
        res['withdraw_table'] = parse_city_table(html, city, ['提取额（亿元）', '提取额', '提取金额'])
        res['loan_table'] = parse_city_table(html, city, ['发放个人住房贷款', '贷款发放额', '发放额', '个人住房贷款'])
    return res


def main():
    import sys
    global REPARSE
    REPARSE = '--reparse' in sys.argv          # 只用本地快照重新解析，不联网
    only = None
    for a in sys.argv:
        if a.startswith('--only='):
            only = set(a.split('=', 1)[1].split(','))
    os.makedirs(RAW_DIR, exist_ok=True)
    db = json.load(open(DB, encoding='utf-8-sig'))
    cities = db['annual_reports']['cities']
    items = [(x['city'], (x.get('report_2024') or {}).get('url')) for x in cities]
    if only:
        items = [i for i in items if i[0] in only]
    prev = {}
    if os.path.exists(OUT) and only:
        prev = {r['city']: r for r in json.load(open(OUT, encoding='utf-8'))}
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(work, items))
    if prev:
        m = {r['city']: r for r in results}
        prev.update(m)
        results = [prev[c] for c, _ in [(x['city'], None) for x in cities] if c in prev]
    json.dump(results, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    ok = sum(1 for r in results if r['ok'])
    hw = sum(1 for r in results if r.get('withdraw'))
    hl = sum(1 for r in results if r.get('loan'))
    print(f'快照/抓取成功 {ok}/{len(results)}；提取额候选 {hw} 城；发放贷款候选 {hl} 城')
    for r in results:
        if not r['ok']:
            print('  FAIL', r['city'], (r.get('err') or '')[:70])


if __name__ == '__main__':
    main()
