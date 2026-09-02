# -*- coding: utf-8 -*-
"""
对 fetch_annual_2024.py 抓取失败的站点做补偿抓取：
 1) 完整浏览器请求头（含 sec-ch-ua / Referer / Accept-Encoding）
 2) 先访问站点首页建立 Cookie 再取正文（应对部分政务 WAF）
 3) 仍失败的城市改用浏览器渲染（见 fetch_annual_2024_browser.py）
产物写入同一份 annual_raw/{city}_2024.html 快照
"""
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_annual_2024 import (DB, RAW_DIR, UA, html2text, fetch as plain_fetch)

FULL_HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'Cache-Control': 'max-age=0',
}


def build_opener():
    """CookieJar + 关闭证书校验（政务站证书链常不完整）+ 关闭环境代理直连"""
    import ssl
    import urllib.request
    cj = http.cookiejar.CookieJar()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    https = urllib.request.HTTPSHandler(context=ctx)
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        https,
        urllib.request.HTTPRedirectHandler(),
        urllib.request.ProxyHandler({}),   # 绕过沙箱代理，减少 502/412
    )


def try_fetch(opener, url, referer=None):
    h = dict(FULL_HEADERS)
    if referer:
        h['Referer'] = referer
        h['Sec-Fetch-Site'] = 'same-origin'
    import gzip
    req = urllib.request.Request(url, headers=h)
    with opener.open(req, timeout=35) as r:
        body = r.read()
        if r.headers.get('Content-Encoding') == 'gzip':
            body = gzip.decompress(body)
    enc = 'utf-8'
    m = re.search(rb'charset=["\']?\s*([\w-]+)', body[:3000], re.I)
    if m:
        e = m.group(1).decode('ascii', 'ignore').lower()
        if e in ('gb2312', 'gbk', 'gb18030'):
            enc = 'gb18030'
    return body.decode(enc, 'ignore')


def work(item):
    city, url = item
    if not url:
        return {'city': city, 'ok': False, 'err': 'NO_URL'}
    opener = build_opener()
    parsed = urllib.parse.urlparse(url)
    home = f'{parsed.scheme}://{parsed.netloc}/'
    html = None
    errs = []
    # 先访问首页拿 cookie
    for base in (home,):
        try:
            try_fetch(opener, base)
            time.sleep(0.4)
        except Exception as ex:
            errs.append('home:' + type(ex).__name__)
    for attempt in range(2):
        try:
            html = try_fetch(opener, url, referer=home if attempt else None)
            break
        except Exception as ex:
            errs.append(f'{type(ex).__name__}: {str(ex)[:60]}')
            time.sleep(1.5)
    if html is None or len(html) < 800:
        return {'city': city, 'ok': False, 'err': '; '.join(errs)[:120]}
    txt = html2text(html)
    if len(txt) < 300:
        return {'city': city, 'ok': False, 'err': 'JS_RENDER(len=%d)' % len(txt)}
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(os.path.join(RAW_DIR, f'{city}_2024.html'), 'w', encoding='utf-8') as f:
        f.write(html)
    return {'city': city, 'ok': True, 'len': len(html), 'txtlen': len(txt)}


def main():
    from concurrent.futures import ThreadPoolExecutor
    db = json.load(open(DB, encoding='utf-8-sig'))
    cities = {x['city']: (x.get('report_2024') or {}).get('url') for x in db['annual_reports']['cities']}
    cand = json.load(open(os.path.join(os.path.dirname(RAW_DIR), 'annual_2024_candidates.json'), encoding='utf-8'))
    todo = [(r['city'], cities.get(r['city'])) for r in cand if not r['ok'] and cities.get(r['city'])]
    print('待补偿抓取:', len(todo))
    with ThreadPoolExecutor(max_workers=6) as ex:
        outs = list(ex.map(work, todo))
    ok = [o for o in outs if o['ok']]
    print(f'补偿成功 {len(ok)}/{len(outs)}')
    for o in outs:
        print(('  OK  ' if o['ok'] else '  FAIL'), o['city'], o.get('txtlen', ''), (o.get('err') or '')[:70])


if __name__ == '__main__':
    main()
