#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回填「允许缓缴年限」等缓缴结构化字段。

背景
----
2026-09-01 的矩阵集成提交（c98dbbc）把顶层 `deferral` 合并进 `deposit.deferred_payment` 时，
只搬运了 supported / legal_basis / conditions，**漏搬了 max_period / procedure / employee_rights**。
前端 site/app.js 的「允许缓缴年限」列读的是 `c.deferral.max_period`，而顶层 deferral 已删除、
deferred_payment 又没有 max_period → 134 城全部显示「待核实」。

数据来源
--------
git 历史提交 a87a78f（矩阵集成前的最后一版）里 deferral 字段组完整，135 城。
134/134 可匹配（历史多出的「阜阳」当年已随城市对齐移除）。

用法
----
    python3 patch_deferred_payment.py            # dry-run，只打印预览
    python3 patch_deferred_payment.py --apply    # 落盘（主库 + app/db.json + site 镜像）

注意
----
- 主库必须 indent=1 重写，否则 diff 会炸到十万行。
- 只新增字段，不覆盖已有的 supported / legal_basis / conditions。
"""
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)                      # project/
ROOT = os.path.dirname(PROJ)                     # 仓库根
DB = os.path.join(ROOT, 'gjj_policy_database.json')
APP_DB = os.path.join(ROOT, 'app', 'db.json')
SITE_DB = os.path.join(ROOT, 'site', 'gjj_policy_database.json')

# 矩阵集成前的最后一个完整版本
HIST_COMMIT = 'a87a78f'
HIST_CACHE = os.path.join(PROJ, 'data', 'db_deferral_hist.json')

# 要回填的字段（纯新增，不覆盖现有）
COPY_FIELDS = ['max_period', 'procedure', 'employee_rights']

_SUFFIX = re.compile(r'(市|自治州|地区|盟|省|自治区|特别行政区|壮族|回族|维吾尔|自治县)$')


def norm(s):
    return _SUFFIX.sub('', str(s or '')).strip()


def detect_indent(path, default=1):
    """读原文件前几行推断缩进空格数。
    各库缩进并不统一：主库是 1 空格，app/db.json 是 2 空格。
    写回时必须保持原样，否则 diff 会从几百行炸到几万行。"""
    try:
        with open(path, encoding='utf-8-sig') as f:
            for line in f:
                s = line.rstrip('\n')
                if s[:1] == ' ' and s.strip():
                    return len(s) - len(s.lstrip(' '))
    except Exception:
        pass
    return default


def load_hist():
    """优先用缓存文件；没有就从 git 导出。"""
    if os.path.exists(HIST_CACHE):
        with open(HIST_CACHE, encoding='utf-8-sig') as f:
            return json.load(f)
    import subprocess
    raw = subprocess.run(
        ['git', 'show', f'{HIST_COMMIT}:gjj_policy_database.json'],
        cwd=ROOT, capture_output=True
    )
    if raw.returncode != 0:
        sys.exit(f'无法从 git 导出 {HIST_COMMIT}：{raw.stderr.decode("utf-8", "ignore")}')
    os.makedirs(os.path.dirname(HIST_CACHE), exist_ok=True)
    with open(HIST_CACHE, 'wb') as f:
        f.write(raw.stdout)
    return json.loads(raw.stdout.decode('utf-8-sig'))


def main():
    apply = '--apply' in sys.argv
    hist_db = load_hist()
    hist = {norm(c['city']): (c.get('deferral') or {}) for c in hist_db['cities']}

    indent_db = detect_indent(DB)          # 先测缩进，写完就测不出来了
    with open(DB, encoding='utf-8-sig') as f:
        db = json.load(f)
    cities = db['cities']

    changed, skipped, unmatched = [], [], []
    for c in cities:
        dp = c.setdefault('deposit', {}).setdefault('deferred_payment', {})
        h = hist.get(norm(c['city']))
        if h is None:
            unmatched.append(c['city'])
            continue
        touched = []
        for k in COPY_FIELDS:
            v = h.get(k)
            if v is None or not str(v).strip():
                continue
            if dp.get(k) and str(dp[k]).strip() == str(v).strip():
                continue                      # 已存在且一致
            dp[k] = v
            touched.append(k)
        if touched:
            changed.append((c['city'], touched))
        else:
            skipped.append(c['city'])

    print(f'匹配：{len(cities) - len(unmatched)}/{len(cities)}；'
          f'本次写入 {len(changed)} 城；无变化 {len(skipped)} 城；未匹配 {len(unmatched)} 城')
    if unmatched:
        print('  未匹配：', unmatched)

    # 回填后「允许缓缴年限」的展示分布
    dist = {}
    for c in cities:
        s = defer_period((c.get('deposit', {}).get('deferred_payment') or {}).get('max_period'))
        dist[s] = dist.get(s, 0) + 1
    print('回填后展示分布：', dist)

    print('\n样例 8 条：')
    shown = 0
    for c in cities:
        mp = (c.get('deposit', {}).get('deferred_payment') or {}).get('max_period')
        if mp and defer_period(mp) != '待核实':
            print(f"  {c['city']:<6} {defer_period(mp):<8} {str(mp)[:60]}")
            shown += 1
            if shown >= 8:
                break
    if not apply:
        print('\n[dry-run] 未落盘。加 --apply 执行。')
        return

    # 备份（显式命名，避免与同日其他批次撞车）
    bak = DB + '.bak_deferred_20260904'
    if not os.path.exists(bak):
        shutil.copy2(DB, bak)
        print('\n已备份 →', os.path.basename(bak))

    with open(DB, 'w', encoding='utf-8-sig') as f:
        json.dump(db, f, ensure_ascii=False, indent=indent_db)

    # 同步前端镜像与部署镜像
    for p in (APP_DB, SITE_DB):
        if not os.path.exists(p):
            print('跳过（不存在）：', p)
            continue
        with open(p, encoding='utf-8-sig') as f:
            m = json.load(f)
        mc = {norm(x['city']): x for x in m.get('cities', [])}
        ind = detect_indent(p)
        n = 0
        for c in cities:
            t = mc.get(norm(c['city']))
            if t is None:
                continue
            tdp = t.setdefault('deposit', {}).setdefault('deferred_payment', {})
            sdp = c.get('deposit', {}).get('deferred_payment') or {}
            for k in COPY_FIELDS:
                if sdp.get(k) is not None:
                    tdp[k] = sdp[k]
                    n += 1
        with open(p, 'w', encoding='utf-8-sig') as f:
            json.dump(m, f, ensure_ascii=False, indent=ind)
        print(f'已同步 {os.path.relpath(p, ROOT)}（indent={ind}，写入 {n} 个字段）')

    print('\n完成。')


def defer_period(mp):
    """复刻 site/app.js 的 deferPeriod()，用于预估前端展示效果。"""
    t = str(mp or '').strip()
    if not t:
        return '待核实'
    if re.search(r'未检索到|未明确|未见明文|未注明|未单列|未在检索结果中明确', t) \
            and not re.search(r'不超过|不得超过|最长', t):
        return '待核实'
    # 政策年份（2021年/2022年）里的数字不是期限，用 (?<!\d) 排除，
    # 否则「最长至2022年12月31日」会被误判成「≤2年」（杭州踩过）。
    if re.search(r'两年|24\s*个?月|(?:不超过|不得超过|最长)[^，。；]{0,4}(?<!\d)2\s*年', t):
        return '≤2年'
    if re.search(r'12\s*个月', t) and not re.search(r'12\s*个?月31日|至.{0,8}12\s*月', t):
        return '≤12个月'
    if re.search(r'一年|(?<!\d)1\s*年|一个住房公积金(结算)?年度|一个公积金年度|按缴存年度申请', t):
        return '≤1年'
    m = re.search(r'(\d+)\s*个?月', t)
    if m and not re.search(r'\d{4}\s*年', t[:t.index(m[0])]):
        return f'≤{m[1]}个月'
    if re.search(r'半年|6\s*个?月', t) and not re.search(r'2022年6月', t):
        return '≤6个月'
    return '待核实'


if __name__ == '__main__':
    main()
