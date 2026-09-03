# -*- coding: utf-8 -*-
"""生成第二批年报链接更新记录 Markdown。"""
import json
import os
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APPLIED = os.path.join(ROOT, 'project/data/annual_report_links_batch2_applied.json')
DB = os.path.join(ROOT, 'gjj_policy_database.json')
OUT = os.path.join(ROOT, '年报链接更新记录_第二批_20260903.md')

JUNK = ('m12333.cn', 'si12333.cn', '51shebao', 'sohu.com', 'o546.cn',
        'news.fang.com', 'qianfan.weijj.cn')


def main():
    ap = json.load(open(APPLIED, encoding='utf-8'))
    db = json.loads(open(DB, encoding='utf-8-sig').read())
    changes = ap['changes']
    by_type = collections.Counter(c['source_type'] for c in changes)

    L = []
    L.append('# 公积金年报链接更新记录（第二批 · 2026-09-03）')
    L.append('')
    L.append('来源文档：`第二次-更新40城链接-标红.xlsx`（9 城，黄底单元格为新增值）')
    L.append('')
    L.append('## 一、概览')
    L.append('')
    L.append('| 项目 | 数量 |')
    L.append('|---|---|')
    L.append('| 涉及城市 | 9（全部匹配成功） |')
    L.append('| **实际更新链接** | **12** |')
    L.append('| — 其中替换为政府网站 | %d |' % by_type.get('政府网站', 0))
    L.append('| — 其中替换为官方媒体 | %d |' % by_type.get('官方媒体', 0))
    L.append('| — 其中替换为其他媒体（非官方） | %d |' % by_type.get('其他媒体', 0))
    L.append('| 文档留空未动 | %d |' % len(ap['unchanged']))
    L.append('| 连带同步 `stats_YYYY.*.source_url` | %d |'
             % sum(len(c['stats_synced']) for c in changes))
    L.append('| 数据库版本 | %s |' % db['version'])
    L.append('')
    L.append('全部 12 条链接已通过 HTTP 核验（状态码 200）并抽查页面标题与正文关键词，'
             '其中 9 条换为政府网站、1 条为官方媒体（丽江日报数字报）、'
             '2 条为其他媒体（已单独说明）。')
    L.append('')

    L.append('## 二、变更明细')
    L.append('')
    L.append('| 城市 | 年度 | 旧链接 | 新链接 | 来源类型 |')
    L.append('|---|---|---|---|---|')
    for c in changes:
        old = c['old_url'] or '（空）'
        L.append('| %s | %s | `%s` | `%s` | %s |'
                 % (c['city'], c['year'], old, c['new_url'], c['source_type']))
    L.append('')

    L.append('## 三、需要关注：2 条非官方来源')
    L.append('')
    L.append('这两条数据的**内容真实性已交叉核对**，仅**载体**不是政府网站，'
             '已在库内标记 `source_type` 以便后续替换。')
    L.append('')
    L.append('| 城市 | 年度 | 载体 | 交叉核对依据 |')
    L.append('|---|---|---|---|')
    L.append('| 丽江 | 2025 | 搜狐 | 缴存额 18.21 亿元，与《云南省住房公积金2025年年度报告》'
             '分城市表「丽江 18.21」一致；提取额 14.87 亿元、贷款发放 9.4 亿元 |')
    L.append('| 泰州 | 2025 | 微靖江（千帆） | 提取额 64.81 亿元、发放贷款 31.36 亿元，'
             '与《江苏省住房公积金2025年年度报告》分城市表「泰州 64.81」一致 |')
    L.append('')
    L.append('已尝试但未找到官方源：')
    L.append('')
    L.append('- 丽江：`gjj.lijiang.gov.cn` 域名不可解析（连接失败），'
             '`lijiang.gov.cn` 与 `szb.lijiang.cn` 均未检索到 2025 年度报告'
             '（2024 年度报告即由丽江日报数字报刊发）。')
    L.append('- 泰州：官网 `gjj.taizhou.gov.cn` 使用 jpaas CMS，'
             '文章 ID 为哈希值且列表由 POST 接口渲染，未检索到 2025 年度报告正文页。')
    L.append('')

    L.append('## 四、来源质量提升与降级说明')
    L.append('')
    L.append('- **朔州 2025/2024 是一次升级**：`zf365.com.cn` 经确认为'
             '**朔州市住房公积金管理中心门户网站**（官方），替换掉原先的搜狐转载。')
    L.append('- **丽江 2025 是载体变更**：原链接指向《云南省住房公积金2025年年度报告》'
             'PDF（省级汇总，非丽江市级），现改为丽江市级年度报告（搜狐转载，图片版）。'
             '内容层级更贴近，但载体权威性下降，故同时订正了标题描述。')
    L.append('- **株洲 2024 为 http → https 升级**，指向同一页面。')
    L.append('')

    L.append('## 五、文档留空未动的条目（6 条）')
    L.append('')
    L.append('| 城市 | 年度 | 库内现有链接 |')
    L.append('|---|---|---|')
    for city, year, reason, url in ap['unchanged']:
        L.append('| %s | %s | `%s` |' % (city, year, url or '（空）'))
    L.append('')

    L.append('## 六、全库残留待清理链接（5 条）')
    L.append('')
    L.append('| 城市 | 年度 | 现有链接 | 说明 |')
    L.append('|---|---|---|---|')
    for c in db['annual_reports']['cities']:
        for yr in (2025, 2024):
            u = (c.get('report_%s' % yr) or {}).get('url') or ''
            if any(j in u for j in JUNK):
                if (c['city'], yr) in (('丽江', 2025), ('泰州', 2025)):
                    note = '第二批新写入，非官方载体但内容已核对'
                else:
                    note = '占位/聚合来源，待下批清理'
                L.append('| %s | %s | `%s` | %s |' % (c['city'], yr, u, note))
    L.append('')

    L.append('## 七、数据安全')
    L.append('')
    L.append('- 落盘前备份：`gjj_policy_database.json.bak_batch2`（第二批前状态）。')
    L.append('- 主库按原始 **indent=1** 重写，避免 diff 被格式化放大。')
    L.append('- 写库后做全量递归 diff：与更新前相比共 **41 项差异，'
             '非预期差异 0**（仅 url / source_url / source_type / verify / '
             'updated_at / version / 丽江2025 标题）。')
    L.append('- 回读校验 12 条全部一致，0 不符。')
    L.append('- 数值类字段（`stats_*.value`）**零改动**。')
    L.append('')

    open(OUT, 'w', encoding='utf-8').write('\n'.join(L))
    print('已生成 ->', os.path.relpath(OUT, ROOT))


if __name__ == '__main__':
    main()
