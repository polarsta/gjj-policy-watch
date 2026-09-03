# -*- coding: utf-8 -*-
"""
通用「只开 PR」脚本：分支已推送到远端后，调用 GitHub REST API 创建 Pull Request。

用法：
    python3 project/scripts/github_open_pr.py <branch> <title_file> <body_file>

设计要点（2026-09-03 网络环境）：
- api.github.com 走系统代理（git config http.proxy / 环境变量 HTTPS_PROXY）可达；
  7890（ClashX）关闭时直连会在 TLS 握手阶段被重置。这里用 curl 自动读代理环境变量，
  比手工 http.client 更省心。
- token 默认从 git credential-osxkeychain 读取，也可用 GITHUB_TOKEN 环境变量覆盖。
- 仓库无 .gitignore，本脚本只负责开 PR，绝不碰工作区文件（提交一律走显式 git add）。
"""
import json
import os
import subprocess
import sys

REPO_OWNER = 'polarsta'
REPO_NAME = 'gjj-policy-watch'


def sh(cmd, stdin=None):
    p = subprocess.run(cmd, shell=True, capture_output=True, input=stdin)
    return p.returncode, p.stdout, p.stderr


def get_token():
    if os.environ.get('GITHUB_TOKEN'):
        return os.environ['GITHUB_TOKEN'].strip()
    rc, out, err = sh('printf "protocol=https\\nhost=github.com\\n\\n" | git credential-osxkeychain get')
    out = out.decode('utf-8', 'replace')
    err = err.decode('utf-8', 'replace')
    for line in out.splitlines():
        if line.startswith('password='):
            return line.split('=', 1)[1].strip()
    raise SystemExit('取不到 GitHub token：%s' % (err or out))


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    branch, title_file, body_file = sys.argv[1:4]
    title = open(title_file, encoding='utf-8').read().strip()
    body = open(body_file, encoding='utf-8').read().strip()
    token = get_token()

    payload = json.dumps({'title': title, 'head': branch, 'base': 'main', 'body': body},
                         ensure_ascii=False)
    cmd = (
        "curl -sS --max-time 60 -X POST "
        "-H 'Authorization: Bearer %s' -H 'Accept: application/vnd.github+json' "
        "-d @- https://api.github.com/repos/%s/%s/pulls"
        % (token, REPO_OWNER, REPO_NAME)
    )
    rc, out, err = sh(cmd, stdin=payload.encode('utf-8'))
    out = out.decode('utf-8', 'replace')
    err = err.decode('utf-8', 'replace')
    if rc != 0:
        raise SystemExit('curl 失败: %s' % err)
    try:
        pr = json.loads(out)
    except json.JSONDecodeError:
        raise SystemExit('响应非 JSON: %s' % out[:500])
    if 'html_url' not in pr:
        raise SystemExit('开 PR 失败: %s' % json.dumps(pr, ensure_ascii=False)[:800])

    print('PR 已创建: %s  (#%s)' % (pr['html_url'], pr['number']))
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), 'project', 'data', 'pr_%s.json'
        % branch.replace('/', '_'))
    json.dump({'branch': branch, 'pr': pr['html_url'], 'number': pr['number']},
              open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('已写入: %s' % out_path)


if __name__ == '__main__':
    main()
