# -*- coding: utf-8 -*-
"""
通过 GitHub REST API 提交改动并开 PR。
用于 git 协议 / api.github.com 走默认网络不通的场景。

网络策略：本环境到 api.github.com 的直连与部分代理通道会在 TLS 握手阶段被重置，
但「HTTP CONNECT 隧道 + HTTP/1.1」可用。脚本会自动探测可用的代理通道（直连 →
git config http.proxy → 环境变量 HTTPS_PROXY），逐个试 /user 取第一个可用者。

用法：
  python3 project/scripts/github_pr_via_api.py              # 建分支 + 开 PR
  python3 project/scripts/github_pr_via_api.py --pr-only    # 分支已推送，只开 PR
token 缺省时从 git credential-osxkeychain 读取。
"""
import base64
import http.client
import json
import os
import ssl
import subprocess
import sys
import urllib.parse

REPO_OWNER = 'polarsta'
REPO_NAME = 'gjj-policy-watch'
API_HOST = 'api.github.com'
API = f'/repos/{REPO_OWNER}/{REPO_NAME}'
PR_ONLY = '--pr-only' in sys.argv

# 相对仓库根路径的文件清单（禁止用 git add -A：仓库无 .gitignore）
FILES = [
    'gjj_policy_database.json',
    'app/db.json',
    'site/app.js',
    'site/index.html',
    'project/scripts/fetch_annual_2024.py',
    'project/scripts/fetch_annual_2024_retry.py',
    'project/scripts/patch_annual_2024.py',
    'project/data/annual_2024_candidates.json',
    'project/data/annual_2024_review.json',
    'project/data/annual_2024_todo.json',
    '年报同比与增减值补录说明_20260902.md',
]
BRANCH = 'feat/annual-yoy-20260902'
PR_TITLE = 'feat(data): 补录2024年提取额/发放贷款并新增同比增幅与增减量'
PR_BODY = """## 改动内容

为「运行数据 · 各市 2025 年度运行统计」表的 **提取额(2025)**、**发放贷款(2025)** 补上与去年（2024 年报）的比较值。

### 1. 数据层（`gjj_policy_database.json` / `app/db.json`）
- `annual_reports.cities[].stats_2024` 新增 `withdraw_amount`（提取额）、`loan_issued`（发放贷款），字段含
  `value`（亿元）、`source_url`、`source_name`、`extract_method`（年报正文 / 省级年报分市表 / 年报原文人工核验）。
- 覆盖率 **89 / 134 城**；其余 45 城因 2024 年报链接失效、政务站 WAF 拦截（HTTP 412 / SSL 握手失败）或页面 JS 渲染未取到正文，留空并在 `note` 中标注原因（前端显示「—」）。
- 取值规则：优先取年报「（二）提取 /（三）贷款」章节内全市口径值（早于「其中：」分中心拆解）；洛阳年报链接指向省级年报，改从「分城市」表格取本市数；天津经年报原文人工核验补录。
- 顶层新增 `annual_reports.yoy_note`，说明同比与增减量均以 2025 / 2024 年报绝对值自行计算。

### 2. 前端（`site/app.js` + `site/index.html`，首次入库）
- 提取额(2025)、发放贷款(2025) 单元格内追加 `同比+X% ▲增加X亿元` / `同比-X% ▼减少X亿元`（红涨绿跌），合计行按可比口径同步计算。
- 「一键导出」CSV 新增 `提取额同比(%)`、`发放贷款同比(%)` 两列。
- 缺失 2024 数据的城市不参与合计行同比计算。

### 3. 脚本与说明
- `project/scripts/fetch_annual_2024.py`（抓取+解析，支持 `--reparse` 仅重解析本地快照）
- `project/scripts/fetch_annual_2024_retry.py`（完整浏览器头 + Cookie 补偿抓取）
- `project/scripts/patch_annual_2024.py`（回填主库并输出待补清单）
- `年报同比与增减值补录说明_20260902.md`（口径、覆盖率、质量校验、45 城待补清单）

### 质量校验
与 2025 年报官方披露同比交叉比对，8 组全部一致：广州提取 +0.8%/+0.76%、广州贷款 +40.2%/+40.25%、
济南提取 +25.7%/+25.70%、济南贷款 +20.4%/+20.38%、苏州贷款 -34.1%/-34.12%、厦门贷款 -54.0%/-54.05%、
湛江贷款 +70.9%/+70.93%、雄安贷款 -66.5%/-66.47%。

### 未纳入本次提交
`project/data/annual_raw/`（17MB 年报 HTML 快照）与 `site/gjj_policy_database.json`、`site/negative_news.json`
（部署用静态快照，页面优先从 GitHub main 拉取最新数据），避免大文件入库与重复 diff。
"""


def _proxy_candidates():
    """候选网络通道：直连 → git config http.proxy → 环境变量。"""
    cands = [None]
    try:
        cfg = subprocess.run(['git', 'config', '--get', 'http.proxy'],
                             capture_output=True, text=True).stdout.strip()
        if cfg:
            cands.append(cfg)
    except Exception:
        pass
    for k in ('https_proxy', 'HTTPS_PROXY', 'http_proxy', 'HTTP_PROXY'):
        v = os.environ.get(k)
        if v and v not in cands:
            cands.append(v)
    # 去重保序
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _connect(proxy):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    if proxy:
        u = urllib.parse.urlparse(proxy if '//' in proxy else 'http://' + proxy)
        conn = http.client.HTTPSConnection(u.hostname, u.port or 80, context=ctx, timeout=120)
        conn.set_tunnel(API_HOST, 443)
    else:
        conn = http.client.HTTPSConnection(API_HOST, 443, context=ctx, timeout=120)
    return conn


def get_token():
    if os.environ.get('GITHUB_TOKEN'):
        return os.environ['GITHUB_TOKEN'].strip()
    out = subprocess.run(
        ['git', 'credential-osxkeychain', 'get'],
        input='protocol=https\nhost=github.com\n\n', capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith('password='):
            return line.split('=', 1)[1].strip()
    raise SystemExit('未取到 GitHub token')


_CHANNEL = {'proxy': None, 'init': False}


def _probe(token, proxy):
    """用 /user 试探某条通道是否可用。"""
    try:
        conn = _connect(proxy)
        conn.request('GET', '/user', headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'gjj-policy-watch-bot',
        })
        resp = conn.getresponse()
        body = resp.read().decode('utf-8', 'ignore')
        conn.close()
        if resp.status == 200:
            return json.loads(body)
    except Exception as e:
        print(f'    通道不可用 [{proxy or "直连"}] {type(e).__name__}: {str(e)[:80]}')
    return None


def _pick_channel(token):
    print('探测可用网络通道：')
    for proxy in _proxy_candidates():
        me = _probe(token, proxy)
        if me:
            print(f'    ✓ {proxy or "直连"} — 身份 {me.get("login")}')
            _CHANNEL['proxy'] = proxy
            _CHANNEL['init'] = True
            return me
    raise SystemExit('所有网络通道均不可用，无法访问 api.github.com')


def req(token, method, path, payload=None):
    if not _CHANNEL['init']:
        _pick_channel(token)
    path = urllib.parse.urlparse(path).path if path.startswith('http') else path
    full = path if path.startswith('/repos/') else API + path
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    conn = _connect(_CHANNEL['proxy'])
    conn.request(method, full, body=data, headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'gjj-policy-watch-bot',
        'Content-Length': str(len(data)) if data else '0',
    })
    resp = conn.getresponse()
    body = resp.read().decode('utf-8', 'ignore')
    conn.close()
    if resp.status >= 400:
        raise SystemExit(f'HTTP {resp.status} {method} {path}\n{body[:800]}')
    return json.loads(body) if body else {}


def create_pr(token):
    prs = req(token, 'GET', f'/pulls?head={REPO_OWNER}:{BRANCH}&state=open')
    if prs:
        print('PR 已存在:', prs[0]['html_url'])
        return prs[0]
    ref = req(token, 'GET', f'/git/ref/heads/{BRANCH}')
    print('远程分支:', BRANCH, ref['object']['sha'][:10])
    pr = req(token, 'POST', '/pulls', {'title': PR_TITLE, 'head': BRANCH, 'base': 'main', 'body': PR_BODY})
    print('PR 已创建:', pr['html_url'])
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       'project', 'data', 'pr_annual_yoy.json')
    json.dump({'branch': BRANCH, 'commit': ref['object']['sha'], 'pr': pr['html_url'], 'number': pr['number']},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    return pr


def main():
    token = get_token()
    if PR_ONLY:
        create_pr(token)
        return
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main_ref = req(token, 'GET', '/git/ref/heads/main')
    base_sha = main_ref['object']['sha']
    base_commit = req(token, 'GET', f'/git/commits/{base_sha}')
    base_tree = base_commit['tree']['sha']
    print('main:', base_sha[:10])

    tree = []
    for rel in FILES:
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            raise SystemExit(f'文件不存在: {rel}')
        raw = open(p, 'rb').read()
        if len(raw) > 90 * 1024 * 1024:
            raise SystemExit(f'文件过大: {rel}')
        blob = req(token, 'POST', '/git/blobs', {
            'content': base64.b64encode(raw).decode('ascii'), 'encoding': 'base64'})
        tree.append({'path': rel, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
        print(f'  blob {rel} ({len(raw)/1024:.0f} KB)')
    new_tree = req(token, 'POST', '/git/trees', {'base_tree': base_tree, 'tree': tree})
    commit = req(token, 'POST', '/git/commits', {
        'message': PR_TITLE + '\n\n- 补录 89 城 2024 年提取额/发放贷款（年报原文与省级分市表）\n'
                             '- 前端提取额(2025)/发放贷款(2025) 追加同比增幅与增减量\n'
                             '- 一键导出 CSV 新增同比列；45 城待补并标注原因',
        'tree': new_tree['sha'], 'parents': [base_sha]})
    print('commit:', commit['sha'][:10])
    try:
        req(token, 'POST', '/git/refs', {'ref': f'refs/heads/{BRANCH}', 'sha': commit['sha']})
        print('分支已创建:', BRANCH)
    except SystemExit as e:
        if 'already exists' in str(e):
            req(token, 'PATCH', f'/git/refs/heads/{BRANCH}', {'sha': commit['sha']})
            print('分支已更新:', BRANCH)
        else:
            raise
    prs = req(token, 'GET', f'/pulls?head={REPO_OWNER}:{BRANCH}&state=open')
    if prs:
        print('PR 已存在:', prs[0]['html_url'])
        return
    pr = req(token, 'POST', '/pulls', {'title': PR_TITLE, 'head': BRANCH, 'base': 'main', 'body': PR_BODY})
    print('PR 已创建:', pr['html_url'])
    json.dump({'branch': BRANCH, 'commit': commit['sha'], 'pr': pr['html_url'], 'number': pr['number']},
              open(os.path.join(root, 'project', 'data', 'pr_annual_yoy.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
