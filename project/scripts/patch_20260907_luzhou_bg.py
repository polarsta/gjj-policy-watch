# -*- coding: utf-8 -*-
"""
2026-09-07 巡检补修②：泸州 case-050 policy_background 改写为泸州地方口径。

背景：前端 site/app.js 的 mineNational() 规则 2 会把 policy_background 命中
/国务院|住建部|人民银行|中央/ 的案例自动挖掘为「全国性政策」（全国徽标 +
「中央部署 · 地方落地」），case-050 背景引用「国务院令第844号」被误归类。

修法：把 policy_background 改写为纯泸州地方口径（不命中中央关键词），
归属从「全国政策」更正为「泸州地方政策」。sources[0] 已在
patch_20260907_luzhou_source.py 中更正为官网原文，本脚本不动 sources。

用法：
  python3 project/scripts/patch_20260907_luzhou_bg.py            # dry-run
  python3 project/scripts/patch_20260907_luzhou_bg.py --apply    # 落盘
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APPLY = '--apply' in sys.argv

OLD_BG = ('新《住房公积金管理条例》（国务院令第844号）2026-09-20施行明确灵活就业人员'
          '可自愿缴存，各地公积金中心加速扩展灵活就业人员代扣代缴合作银行范围，'
          '破解按月缴存扣款渠道单一问题。')
NEW_BG = ('泸州市灵活就业人员可自愿缴存住房公积金并选择签约银行按月代扣代缴；'
          '此前扣缴渠道相对单一，市公积金中心持续扩大代扣代缴合作银行范围，'
          '拓宽灵活就业人员缴款渠道。')

# 前端 mineNational 规则 2 的中央关键词，改写后必须不再命中
NAT_RE = re.compile(r'国务院|住建部|人民银行|中央')

JSON_TARGETS = [
    'gjj_policy_database.json',
    'app/db.json',
    'research/cases.json',
    'site/gjj_policy_database.json',
]
MD_TARGET = '商机案例库.md'

diffs = []


def detect_indent(path):
    """取全文件最小正缩进为基础缩进（不能取第一个缩进 key 的列号，
    research/cases.json 是 list 包 dict，首 key 在第 4 列而基础缩进是 2）。"""
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


def write_json(path, obj, indent, trailing_newline):
    """按原文件 BOM / EOF 换行状态写回（主库与镜像原本末尾无换行）。"""
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
    if case.get('policy_background') != OLD_BG:
        if NAT_RE.search(case.get('policy_background') or ''):
            print('  [警告] %s case-050 背景与预期不符且仍命中中央关键词，需人工检查' % rel)
        else:
            print('  [无变化] %s' % rel)
        return

    assert not NAT_RE.search(NEW_BG), '新背景文本命中中央关键词，禁止写入'
    diffs.append((rel, 'case-050.policy_background', OLD_BG[:40] + '…', NEW_BG[:40] + '…'))
    case['policy_background'] = NEW_BG

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
    old_line = '- **政策背景**：%s' % OLD_BG
    new_line = '- **政策背景**：%s' % NEW_BG
    if old_line in text:
        diffs.append((MD_TARGET, 'case-050 政策背景行', OLD_BG[:40] + '…', NEW_BG[:40] + '…'))
        if APPLY:
            open(path, 'w', encoding='utf-8').write(text.replace(old_line, new_line))
        print('  [%s] %s' % ('已写入' if APPLY else '待写入', MD_TARGET))
    elif NEW_BG in text:
        print('  [无变化] %s' % MD_TARGET)
    else:
        print('  [警告] %s 未匹配到目标行，需人工检查' % MD_TARGET)


def main():
    print('泸州 case-050 政策背景改写补丁（全国口径→泸州地方口径）%s'
          % ('（落盘）' if APPLY else '（dry-run，加 --apply 落盘）'))
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
