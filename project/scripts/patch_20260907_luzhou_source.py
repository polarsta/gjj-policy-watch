# -*- coding: utf-8 -*-
"""
2026-09-07 巡检补修：泸州 case-050 来源 URL 与归属属性更正。

背景：case-050（泸州新增农行灵活就业按月扣缴）的 sources[0] 原挂 m12333.cn
（人社通转载，垃圾占位域名，实探 HTTP 412），归属呈「全国性政策来源」。
现更正为泸州市住房公积金管理中心官网原文，归属改为泸州地方政策。

已核验 https://zfgjj.luzhou.cn/tzgg/content_34616 ：
  HTTP 200（需浏览器 UA），标题《泸州市住房公积金管理中心 关于新增灵活就业人员
  住房公积金按月扣缴业务合作银行的通知》，正文与案例口径一致（2026-09-07 起新增农行，
  工农/交行/邮储/农行四家开通按月扣缴）。

同时递进版本号 1.5.4 → 1.5.5：此前 main 与巡检分支同为 v1.5.4 但内容不同
（49 vs 56 案例），属同名撞车，需递进才能被前端 version 比对正确识别。

用法：
  python3 project/scripts/patch_20260907_luzhou_source.py            # dry-run
  python3 project/scripts/patch_20260907_luzhou_source.py --apply    # 落盘
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APPLY = '--apply' in sys.argv

OLD_URL = 'https://m12333.cn/policy/srswp.html'
NEW_URL = 'https://zfgjj.luzhou.cn/tzgg/content_34616'
OLD_TITLE = '泸州市 关于新增灵活就业人员住房公积金按月扣缴业务合作银行的通知（人社通转载）'
NEW_TITLE = '泸州市住房公积金管理中心 关于新增灵活就业人员住房公积金按月扣缴业务合作银行的通知'

# 相对仓库根；site/ 镜像不在 git 内但需同步（部署数据源）
JSON_TARGETS = [
    'gjj_policy_database.json',
    'app/db.json',
    'research/cases.json',
    'site/gjj_policy_database.json',
]
MD_TARGET = '商机案例库.md'

diffs = []


def detect_indent(path):
    """自适应缩进：主库=1 空格、app/db.json=2、research/cases.json=2、site 镜像=2。
    写死 indent 会把 diff 炸到几万行。

    ⚠️ 坑：不能取「第一个缩进的 key」的列号。research/cases.json 是 list 包 dict，
    首个 "key" 出现在第 4 列（[{ → { → "id"），而真实基础缩进是 2。
    正确做法：取全文件最小的正缩进作为基础缩进。"""
    raw = open(path, encoding='utf-8-sig').read()
    levels = set()
    for ln in raw.split('\n'):
        m = re.match(r'^( +)\S', ln)
        if m:
            levels.add(len(m.group(1)))
        if len(levels) > 50:
            break
    return min(levels) if levels else 2


def has_bom(path):
    with open(path, 'rb') as f:
        return f.read(3) == b'\xef\xbb\xbf'


def write_json(path, obj, indent, trailing_newline=True):
    """按原文件的 BOM / EOF 换行状态写回，避免产生无关 diff。
    ⚠️ 本项目主库与两个镜像原本都「末尾无换行」，补换行会多出一段无关 diff。"""
    bom = has_bom(path)
    text = json.dumps(obj, ensure_ascii=False, indent=indent)
    if trailing_newline:
        text += '\n'
    if bom:
        with open(path, 'wb') as f:
            f.write(b'\xef\xbb\xbf')
            f.write(text.encode('utf-8'))
    else:
        with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)


def find_case050(obj):
    """在任意 dict/list 嵌套里找 case-050（各文件结构不同：主库在 case_library.cases，
    research/cases.json 自身就是 list）。"""
    if isinstance(obj, list):
        for x in obj:
            if isinstance(x, dict) and x.get('id') == 'case-050':
                return x
            r = find_case050(x)
            if r:
                return r
    elif isinstance(obj, dict):
        if obj.get('id') == 'case-050':
            return obj
        for v in obj.values():
            r = find_case050(v)
            if r:
                return r
    return None


def patch_json(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        print('  [跳过] 文件不存在: %s' % rel)
        return
    indent = detect_indent(path)
    orig = open(path, encoding='utf-8-sig').read()
    trailing_newline = orig.endswith('\n')
    db = json.load(open(path, encoding='utf-8-sig'))

    case = find_case050(db)
    if not case:
        print('  [跳过] 未找到 case-050: %s' % rel)
        return

    changed = False
    src = case['sources'][0]
    if src.get('url') != NEW_URL:
        diffs.append((rel, 'case-050.sources[0].url', src.get('url'), NEW_URL))
        src['url'] = NEW_URL
        changed = True
    if src.get('title') != NEW_TITLE:
        diffs.append((rel, 'case-050.sources[0].title', src.get('title'), NEW_TITLE))
        src['title'] = NEW_TITLE
        changed = True

    # 仅带 version 字段的文件（主库与两个镜像）递进版本；research/cases.json 无此字段
    if isinstance(db, dict) and 'version' in db and db['version'] == '1.5.4':
        diffs.append((rel, 'version', db['version'], '1.5.5'))
        db['version'] = '1.5.5'
        changed = True

    if not changed:
        print('  [无变化] %s' % rel)
        return

    if APPLY:
        write_json(path, db, indent, trailing_newline)
    print('  [%s] %s (indent=%d%s%s)' % ('已写入' if APPLY else '待写入', rel, indent,
                                         ', BOM' if has_bom(path) else '',
                                         '' if trailing_newline else ', EOF无换行'))


def patch_md():
    path = os.path.join(ROOT, MD_TARGET)
    if not os.path.exists(path):
        print('  [跳过] 文件不存在: %s' % MD_TARGET)
        return
    text = open(path, encoding='utf-8').read()
    old_line = '  - [%s](%s)（2026-09-04）' % (OLD_TITLE, OLD_URL)
    new_line = '  - [%s](%s)（2026-09-04）' % (NEW_TITLE, NEW_URL)
    if old_line in text:
        diffs.append((MD_TARGET, 'case-050 来源行', old_line.strip(), new_line.strip()))
        if APPLY:
            open(path, 'w', encoding='utf-8').write(text.replace(old_line, new_line))
        print('  [%s] %s' % ('已写入' if APPLY else '待写入', MD_TARGET))
    elif NEW_URL in text:
        print('  [无变化] %s' % MD_TARGET)
    else:
        print('  [警告] %s 未匹配到目标行，需人工检查' % MD_TARGET)


def main():
    print('泸州 case-050 来源更正补丁%s' % ('（落盘）' if APPLY else '（dry-run，加 --apply 落盘）'))
    print('-' * 70)
    for rel in JSON_TARGETS:
        patch_json(rel)
    patch_md()
    print('-' * 70)
    if diffs:
        print('字段级 diff（共 %d 处）：' % len(diffs))
        for rel, field, old, new in diffs:
            print('  %s :: %s' % (rel, field))
            print('    - %s' % old)
            print('    + %s' % new)
    else:
        print('无待变更内容')
    print('-' * 70)
    print('APPLY=%s' % APPLY)


if __name__ == '__main__':
    main()
