# -*- coding: utf-8 -*-
"""
批量抓取 + 解析 45 城 2024 年度公积金年报的「提取额」与「发放个人住房贷款」。

用法：
  /Users/xuyixuan/.workbuddy/binaries/python/envs/default/bin/python fetch_annual_45.py [--city 上海 深圳] [--verbose]

流程：
  1. httpget 直连抓取（带浏览器请求头）；
  2. 失败（412/403/无关键词）的 URL 收集起来，交给 cdp_fetch 批量渲染；
  3. HTML/PDF → 纯文本 → annual_parse 解析；
  4. 文本落盘 project/data/annual_45_txt/<城市>.txt 便于人工核对；
  5. 结果写入 project/data/annual_45_result.json。
"""
import sys
import os
import re
import json
import time
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import httpget
import annual_parse

PROJ = os.path.dirname(HERE)          # .../gjj-policy-watch/project
SRC = os.path.join(PROJ, 'data', 'annual_src_45.json')
OUTDIR = os.path.join(PROJ, 'data', 'annual_45_txt')
OUTJSON = os.path.join(PROJ, 'data', 'annual_45_result.json')

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'close',
}

KEYWORDS = ('提取', '发放个人住房贷款', '贷款')


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
    """把全角数字/单位归一，方便正则。"""
    t = t.replace('％', '%').replace('，', '，')
    return re.sub(r'[ \t\u3000]+', '', t)


def fetch_one(url, kind='html', timeout=25):
    """返回 (text, meta)。kind='pdf' 时走 pypdf。"""
    if kind == 'pdf':
        import io
        r = httpget_raw(url, timeout=timeout)
        if not r or r['status'] != 200 or not r['body']:
            return '', {'status': (r or {}).get('status'), 'error': (r or {}).get('error')}
        try:
            from pypdf import PdfReader
            rd = PdfReader(io.BytesIO(r['body']))
            txt = '\n'.join((p.extract_text() or '') for p in rd.pages)
            return txt, {'status': 200, 'bytes': len(r['body'])}
        except Exception as ex:
            return '', {'status': 200, 'error': f'pdf:{type(ex).__name__}: {ex}'}
    r = httpget.get(url, timeout=timeout, headers=HEADERS)
    if r['status'] != 200 or not r['text']:
        return '', {'status': r['status'], 'error': r['error'] or 'empty'}
    return html2text(r['text']), {'status': r['status'], 'chars': len(r['text'])}


def httpget_raw(url, timeout=25):
    """取原始字节（PDF 用）。复用 httpget 的底层，改成返回 body。"""
    import urllib.parse
    import socket as _s
    u = urllib.parse.urlparse(url)
    tls = u.scheme == 'https'
    port = u.port or (443 if tls else 80)
    try:
        sock = _s.create_connection((u.hostname, port), timeout=timeout)
        if tls:
            sock = httpget._ctx().wrap_socket(sock, server_hostname=u.hostname)
        path = u.path or '/'
        if u.query:
            path += '?' + u.query
        req = (f'GET {path} HTTP/1.1\r\nHost: {u.hostname}\r\n'
               f'User-Agent: {UA}\r\nAccept: */*\r\nConnection: close\r\n\r\n')
        sock.sendall(req.encode())
        raw = httpget._read_all(sock, timeout)
        sock.close()
        head, _, body = raw.partition(b'\r\n\r\n')
        hl = head.decode('iso-8859-1').lower()
        status = int(re.search(r'HTTP/1\.[01]\s+(\d+)', head.decode('iso-8859-1')).group(1))
        if 'transfer-encoding: chunked' in hl:
            body = httpget._unchunk(body)
        if 'content-encoding: gzip' in hl:
            import gzip
            body = gzip.decompress(body)
        elif 'content-encoding: deflate' in hl:
            import zlib
            body = zlib.decompress(body, -zlib.MAX_WBITS)
        return {'status': status, 'body': body}
    except Exception as ex:
        return {'status': 0, 'body': b'', 'error': f'{type(ex).__name__}: {ex}'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--city', nargs='*', default=None)
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--cdp', action='store_true', help='对直连失败的用 CDP 渲染重试')
    args = ap.parse_args()

    src = json.load(open(SRC, encoding='utf-8'))
    cities = args.city or [k for k in src if not k.startswith('_')]
    os.makedirs(OUTDIR, exist_ok=True)

    results = {}
    failed = []   # [(city, url, kind)] 待 CDP

    for city in cities:
        items = sorted(src.get(city, []), key=lambda x: x.get('priority', 9))
        if not items:
            print(f'== {city} == 无源')
            continue
        got = None
        for it in items:
            url, kind = it['url'], it.get('kind', 'html')
            if kind == 'provincial':
                print(f'== {city} == 跳过（省级汇总，需人工切表）: {url[:70]}')
                continue
            txt, meta = fetch_one(url, kind)
            ok = txt and any(k in txt for k in KEYWORDS)
            print(f'== {city} == [{meta.get("status")}] chars={len(txt)} 命中={bool(ok)} {url[:78]}')
            if ok:
                t = normalize(txt)
                r = annual_parse.parse(t, verbose=args.verbose)
                r.update({'url': url, 'title': it['title'], 'type': it['type'],
                          'meta': meta, 'text_len': len(t)})
                got = r
                open(os.path.join(OUTDIR, f'{city}.txt'), 'w', encoding='utf-8').write(t)
                print(f'    提取额={r["withdraw"]}  贷款={r["loan"]}')
                break
            failed.append((city, url, kind))
        results[city] = got or {'withdraw': None, 'loan': None, 'url': None}

    json.dump(results, open(OUTJSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'\n结果 → {OUTJSON}')
    ok = sum(1 for v in results.values() if v.get('withdraw') and v.get('loan'))
    print(f'双值齐全 {ok}/{len(results)}')

    if args.cdp and failed:
        print(f'\n待 CDP 重试 {len(failed)} 条：')
        for c, u, k in failed:
            print(f'  {c}\t{u}')


if __name__ == '__main__':
    main()
