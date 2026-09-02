# -*- coding: utf-8 -*-
"""
轻量 HTTP/1.1 客户端（直连）。

为什么不用 urllib / requests：
  本环境常见「仓库里配了死代理 http.proxy=127.0.0.1:7890（ClashX）」，urllib 会去连它
  然后卡死 33 秒；而直连其实是通的。这里直接用 socket 建连，绕开 urllib 的代理逻辑。

支持：HTTPS（关闭证书校验，政务站证书链常不完整）、gzip/deflate、chunked、
     重定向跟随、GBK/UTF-8 编码自动识别。
"""
import gzip
import re
import socket
import ssl
import urllib.parse
import zlib

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _read_all(sock, timeout):
    sock.settimeout(timeout)
    chunks = []
    while True:
        try:
            b = sock.recv(65536)
        except socket.timeout:
            break
        if not b:
            break
        chunks.append(b)
    return b''.join(chunks)


def _unchunk(body):
    """去除 HTTP chunked 分块长度前缀。"""
    out = bytearray()
    pos = 0
    while True:
        i = body.find(b'\r\n', pos)
        if i < 0:
            break
        try:
            size = int(body[pos:i].split(b';')[0].strip(), 16)
        except ValueError:
            break
        pos = i + 2
        if size == 0:
            break
        out += body[pos:pos + size]
        pos += size + 2
    return bytes(out)


def _decode(body, head_lower):
    if 'content-encoding: gzip' in head_lower:
        try:
            body = gzip.decompress(body)
        except Exception:
            pass
    elif 'content-encoding: deflate' in head_lower:
        for f in (lambda b: zlib.decompress(b), lambda b: zlib.decompress(b, -15)):
            try:
                body = f(body)
                break
            except Exception:
                continue
    m = re.search(rb'charset=["\']?\s*([\w-]+)', body[:4000], re.I)
    enc = 'utf-8'
    if m:
        e = m.group(1).decode('ascii', 'ignore').lower()
        if e in ('gb2312', 'gbk', 'gb18030'):
            enc = 'gb18030'
    # meta charset 经常与真实编码不符（政务站尤其常见：声明 gb2312 实为 utf-8，反之亦然）。
    # 严格解码两种候选，取「合法字符占比」更高的那个，避免出现"鍗楅氫綇鎴垮叕绉"式乱码。
    cands = [enc] + [c for c in ('utf-8', 'gb18030') if c != enc]
    best, best_score = None, -1.0
    for c in cands:
        try:
            s = body.decode(c)          # 严格模式，解不开就是不对
        except UnicodeDecodeError:
            continue
        if not s:
            continue
        score = _legible(s)
        if score > best_score:
            best, best_score = s, score
    if best is not None:
        return best
    return body.decode(enc, 'ignore')


def _legible(s, sample=6000):
    """合法字符占比：ASCII + 中日韩统一表意文字 + 中文标点 + 数字。"""
    sub = s[:sample]
    if not sub:
        return 0.0
    good = 0
    for ch in sub:
        o = ord(ch)
        if o < 0x80:
            good += 1
        elif 0x4E00 <= o <= 0x9FFF:      # CJK 统一表意文字
            good += 1
        elif 0x3000 <= o <= 0x303F:      # 中文标点
            good += 1
        elif 0xFF00 <= o <= 0xFFEF:      # 全角
            good += 1
    return good / len(sub)


def get(url, timeout=25, max_redirect=5, headers=None):
    """返回 dict: {status, url, text, error}。status 为 0 表示网络层失败。"""
    for _ in range(max_redirect + 1):
        u = urllib.parse.urlparse(url)
        tls = u.scheme == 'https'
        port = u.port or (443 if tls else 80)
        path = u.path or '/'
        if u.query:
            path += '?' + u.query
        try:
            sock = socket.create_connection((u.hostname, port), timeout=timeout)
            if tls:
                sock = _ctx().wrap_socket(sock, server_hostname=u.hostname)
            h = {
                'Host': u.hostname if u.port is None else f'{u.hostname}:{u.port}',
                'User-Agent': UA,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'close',
            }
            if headers:
                h.update(headers)
            req = 'GET %s HTTP/1.1\r\n' % path
            req += ''.join(f'{k}: {v}\r\n' for k, v in h.items()) + '\r\n'
            sock.sendall(req.encode('latin-1', 'ignore'))
            raw = _read_all(sock, timeout)
            sock.close()
        except Exception as ex:
            return {'status': 0, 'url': url, 'text': '', 'error': f'{type(ex).__name__}: {ex}'}

        head, _, body = raw.partition(b'\r\n\r\n')
        hl = head.decode('iso-8859-1').lower()
        m = re.match(r'HTTP/[\d.]+ (\d+)', head.decode('iso-8859-1'))
        status = int(m.group(1)) if m else 0
        if 'transfer-encoding: chunked' in hl:
            body = _unchunk(body)
        if status in (301, 302, 303, 307, 308):
            loc = re.search(r'(?i)\r\nlocation:\s*(\S+)', head.decode('iso-8859-1'))
            if loc:
                url = urllib.parse.urljoin(url, loc.group(1).strip())
                continue
        return {'status': status, 'url': url, 'text': _decode(body, hl), 'error': ''}
    return {'status': 0, 'url': url, 'text': '', 'error': 'too many redirects'}


if __name__ == '__main__':
    import sys
    r = get(sys.argv[1] if len(sys.argv) > 1 else 'https://www.baidu.com/')
    print(r['status'], len(r['text']), r['error'])
