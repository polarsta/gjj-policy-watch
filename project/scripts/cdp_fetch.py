# -*- coding: utf-8 -*-
"""
用 Chrome DevTools Protocol 批量渲染页面。

为什么要它：
  m12333.cn 等站点有 JS 挑战（HTTP 412 + /akeyjs 脚本）和登录墙，urllib/curl 拿不到正文；
  而每个页面单独 `--headless=new --dump-dom` 启动一次 Chrome 要 1~3 分钟，18 个城市跑不完。
  CDP 方案只启动一次 Chrome，之后每个 URL 开一个 tab，几十秒内可批量完成。

配合登录态：
  先用有头 Chrome 登录（--user-data-dir=/tmp/gjj-chrome-profile），登录后把该目录复制一份
  （去掉 Singleton 锁）交给本脚本复用 cookie。

用法：
  python3 project/scripts/cdp_fetch.py            # 按 URLS 列表批量抓
  作为库：from cdp_fetch import CDPSession
"""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request

# websocket 是 CDP 唯一强依赖，延后到 start_chrome 阶段再 import
# （这样 import cdp_fetch.html2text 等纯文本函数就不会被强制要求）

CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
DEFAULT_PROFILE = '/tmp/gjj-hl'


def prepare_profile(src='/tmp/gjj-chrome-profile', dst=DEFAULT_PROFILE):
    """复制登录过的 profile，去掉单例锁，供无头实例复用 cookie。"""
    if not os.path.exists(src):
        return src
    if os.path.abspath(src) != os.path.abspath(dst):
        if os.path.exists(dst):
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst, symlinks=True)
    for name in ('SingletonLock', 'SingletonCookie', 'SingletonSocket'):
        for p in (os.path.join(dst, name), os.path.join(dst, 'Default', name)):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    return dst


def start_chrome(port=9222, user_data_dir=DEFAULT_PROFILE, timeout=60):
    proc = subprocess.Popen(
        [CHROME, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
         '--disable-extensions', '--disable-background-networking',
         # Chrome 111+ 默认拒绝带 Origin 头的 WebSocket，不加这个会 403
         '--remote-allow-origins=*',
         f'--remote-debugging-port={port}', f'--user-data-dir={user_data_dir}', 'about:blank'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f'http://127.0.0.1:{port}/json/version'
    for _ in range(int(timeout * 2)):
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                info = json.loads(r.read().decode())
            return proc, info['webSocketDebuggerUrl']
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError('Chrome 进程已退出')
            time.sleep(0.5)
    raise RuntimeError('Chrome 调试端口未就绪')


class CDPSession:
    def __init__(self, ws_url, timeout=120):
        import websocket  # 延迟导入：只在真正要用 CDP 时才需要
        # suppress_origin：不发 Origin 头，避免被 Chrome 的 origin 校验拒绝
        self.ws = websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)
        self._id = 0

    def send(self, method, params=None, session_id=None):
        self._id += 1
        msg = {'id': self._id, 'method': method, 'params': params or {}}
        if session_id:
            msg['sessionId'] = session_id
        self.ws.send(json.dumps(msg))
        while True:
            resp = json.loads(self.ws.recv())
            if resp.get('id') == self._id:
                if 'error' in resp:
                    raise RuntimeError(f'{method}: {resp["error"].get("message")}')
                return resp.get('result', {})
            # 非本请求的消息（事件通知）直接丢弃

    def fetch(self, url, wait=5.0, scroll=True, max_wait=25):
        """打开 URL，等 JS 渲染，返回完整 HTML。"""
        tid = self.send('Target.createTarget', {'url': url})['targetId']
        sid = self.send('Target.attachToTarget', {'targetId': tid, 'flatten': True})['sessionId']
        try:
            self.send('Page.enable', {}, sid)
            time.sleep(wait)
            if scroll:  # 触发懒加载
                for _ in range(3):
                    self.send('Runtime.evaluate', {
                        'expression': 'window.scrollTo(0, document.body.scrollHeight)',
                        'returnByValue': True}, sid)
                    time.sleep(0.4)
            deadline = time.time() + max_wait
            html = ''
            while time.time() < deadline:
                r = self.send('Runtime.evaluate', {
                    'expression': 'document.documentElement.outerHTML',
                    'returnByValue': True}, sid)
                html = r.get('result', {}).get('value') or ''
                if html and len(html) > 5000:
                    break
                time.sleep(1.5)
            return html
        finally:
            try:
                self.send('Target.closeTarget', {'targetId': tid})
            except Exception:
                pass

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def html2text(html):
    t = re.sub(r'(?is)<script.*?</script>|<style.*?</style>|<!--.*?-->', ' ', html)
    t = re.sub(r'(?i)</(p|div|tr|td|th|br|li|h\d)>', '\n', t)
    t = re.sub(r'<[^>]+>', '', t)
    for a, b in (('&nbsp;', ' '), ('&#160;', ' '), ('&emsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>')):
        t = t.replace(a, b)
    t = re.sub(r'[ \t\u3000]+', ' ', t)
    t = re.sub(r'\n\s*\n+', '\n', t)
    return t.strip()


def batch(urls, wait=5.0, profile=DEFAULT_PROFILE, outdir=None, port=9222):
    """批量抓取，返回 {url: {'text': 正文, 'html': 原始, 'error': ''}}"""
    profile = prepare_profile(dst=profile)
    proc, ws_url = start_chrome(port=port, user_data_dir=profile)
    out = {}
    try:
        sess = CDPSession(ws_url)
        for u in urls:
            try:
                html = sess.fetch(u, wait=wait)
                out[u] = {'html': html, 'text': html2text(html), 'error': ''}
                print(f'  {len(html):>8} 字符  {u[:70]}', flush=True)
            except Exception as e:
                out[u] = {'html': '', 'text': '', 'error': f'{type(e).__name__}: {e}'}
                print(f'  FAIL              {u[:70]}  {type(e).__name__}', flush=True)
            if outdir:
                os.makedirs(outdir, exist_ok=True)
                name = re.sub(r'[^A-Za-z0-9]+', '_', u)[-70:] + '.html'
                open(os.path.join(outdir, name), 'w', encoding='utf-8').write(out[u]['html'])
        sess.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    return out


if __name__ == '__main__':
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    if not args:
        print('用法: python3 cdp_fetch.py URL [URL ...]')
        sys.exit(1)
    res = batch(args, wait=float(next((a.split('=')[1] for a in sys.argv if a.startswith('--wait=')), 5.0)))
    for u, r in res.items():
        print('=' * 70)
        print(u, '|', len(r['text']), '字符 |', r['error'])
        print(r['text'][:1500])
