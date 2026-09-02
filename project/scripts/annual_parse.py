# -*- coding: utf-8 -*-
"""
公积金年报数值解析器。

背景：住房公积金年报（2024 年度，2025 年发布）里「提取额」「发放个人住房贷款」
的表述方式各城市不一致，且存在大量会误导正则的近似表述：
  - 累计口径： "2024年末，累计发放个人住房贷款333.05万笔13535.24亿元"
  - 异地贷款： "发放异地贷款1066笔12.50亿元"
  - 贴息贷款： "发放住房公积金贴息贷款…"
  - 分中心拆解： "其中，市中心发放个人住房贷款3.58万笔239.76亿元，省直分中心…"
  - 笔数在金额前： "发放个人住房贷款10.90万笔951.23亿元"  ← 最容易错抓成 10.90 或 3.0

设计原则：
  1. 同一句话里先看「窗口上下文」，窗口内出现否定词（累计/异地/贴息/公转商/项目贷款/回收/其中）
     则跳过该候选；
  2. 全市口径优先：取「(一)机构概况」之后、(二)之前，且位置最靠前、且晚于「2024年」（非"2024年末"）的候选；
  3. 若原文带「同比分别…X%、…Y%」，金额同比是第二个百分数，可用于校验方向。
"""
import re

# ---------- 否定窗口 ----------
NEG = re.compile(
    r'(?:累计|异地|贴息|公转商|项目贷款|回收|其中|分中心|铁路|油田|省直|矿务局|上年同期|同期)'
)

# ---------- 提取额 ----------
# 常见表述：
#   "2024年，提取额1693.90亿元"        "提取金额 1693.9 亿元"
#   "全年提取1693.90亿元"              "提取住房公积金1693.90亿元"
#   "64.36万名缴存职工提取住房公积金107.16亿元"
PAT_WITHDRAW = [
    # 「提取额/提取金额 X 亿元」——最规范
    re.compile(r'(?:提取额|提取金额|提取总额(?!.*累计)|提取资金总额)\s*[为：:]*\s*(\d[\d,]*\.?\d*)\s*亿元'),
    # 「提取住房公积金57.14万人共233.40亿元」——福州式：人数 + 共 + 金额
    re.compile(r'(?:提取|提取了)\s*(?:住房)?公积金\s*[\d,.]*\s*万?\s*[人户]\s*[^。；]{0,8}?(\d[\d,]*\.?\d*)\s*亿元'),
    # 「提取(了)?住房公积金 X 亿元」——前面可带人数/笔数
    re.compile(r'(?:提取(?:了)?|共提取|累计提取(?!.*累计))(?:住房)?公积金?\s*[\d,.]*\s*万?[人户]?[次]?\s*[，、]?\s*(\d[\d,]*\.?\d*)\s*亿元'),
    # 「提取 X 亿元」/「提取 30.96 亿元」——咸阳式
    re.compile(r'提取\s*[^\d]{0,12}?(\d[\d,]*\.?\d*)\s*亿元'),
    # 「X 亿元，…提取」反向
    re.compile(r'(\d[\d,]*\.?\d*)\s*亿元[，。；\s]{0,4}[^。；]{0,20}?提取(?:金额|额)?'),
]

# ---------- 发放个人住房贷款 ----------
# 核心格式：「发放个人住房贷款 <笔数>万笔 <金额>亿元」
PAT_LOAN = [
    # 笔数+金额：发放个人住房贷款10.90万笔951.23亿元（上海）
    re.compile(r'发放个人住房贷款\s*[\d,]*\.?\d*\s*(?:万)?\s*[笔户次]\s*[，、]?\s*(?:共计|共|合计)?\s*(\d[\d,]*\.?\d*)\s*亿元'),
    # 红河式：发放个人住房贷款0.47万笔，发放额23.87亿元
    re.compile(r'发放个人住房贷款[^。；]{0,25}?发放额?\s*[为：:]*\s*(\d[\d,]*\.?\d*)\s*亿元'),
    # 笔数+金额（笔数用 16,063 笔）
    re.compile(r'发放个人住房贷款\s*[\d,]*\.?\d*\s*[笔户次]\s*[，、]?\s*(?:共)?\s*(\d[\d,]*\.?\d*)\s*亿元'),
    # 只有金额：发放个人住房贷款289.40亿元
    re.compile(r'发放个人住房贷款\s*[^\d]{0,10}?(?:共)?\s*(\d[\d,]*\.?\d*)\s*亿元'),
    # 发放住房公积金贷款 / 发放公积金个人住房贷款
    re.compile(r'发放(?:住房公积金|公积金)?(?:个人住房)?贷款\s*[\d,]*\.?\d*\s*(?:万)?\s*[笔户次]?\s*[，、]?\s*(\d[\d,]*\.?\d*)\s*亿元'),
    # 贷款发放额 X 亿元
    re.compile(r'(?:个人住房)?贷款发放额\s*[为：:]*\s*(\d[\d,]*\.?\d*)\s*亿元'),
    re.compile(r'(?:发放|新增)(?:个人住房)?贷款额?\s*[为：:]*\s*(\d[\d,]*\.?\d*)\s*亿元'),
]


def _num(s):
    try:
        return float(str(s).replace(',', '').replace('，', ''))
    except Exception:
        return None


def _window(text, pos, before=38, after=26):
    a = max(0, pos - before)
    return text[a:pos + after]


_SENT_SPLIT = re.compile(r'[。；;！!？?\n]')


def _is_bad(text, pos, before=90):
    """
    候选位置所在「句子」内是否出现否定词。

    注意：不能简单地取 pos 前 N 个字符——像红河的
    「…最高额度100万元，其中，单缴存职工最高额度70万元。发放个人住房贷款0.47万笔，发放额23.87亿元」
    里 "其中" 出现在上一句，若按固定窗口判断就会误杀。所以先切到本句起点再判。
    """
    seg = text[max(0, pos - before):pos]
    # 只保留最后一个句子分隔符之后的内容 = 候选所在句的前半段
    parts = _SENT_SPLIT.split(seg)
    cur = parts[-1] if parts else seg
    return bool(NEG.search(cur))


def _clean_num(v):
    if v is None:
        return None
    # 明显是笔数（小于1万笔的量级）或异常值过滤在调用侧做
    return round(v, 2)


def extract_withdraw(text, verbose=False):
    """返回 (value, context)。无有效候选返回 (None, None)。"""
    cands = []
    for i, p in enumerate(PAT_WITHDRAW):
        for m in p.finditer(text):
            v = _num(m.group(1))
            if v is None or v <= 0:
                continue
            ctx = _window(text, m.start())
            if _is_bad(text, m.start(), len(m.group(0))):
                if verbose:
                    print(f'    [提·跳过] {v} @ {m.start()} 否定词 | {ctx}')
                continue
            # 排除「2024年末累计」：检查是否紧跟"末"字
            pre = text[max(0, m.start() - 60):m.start()]
            if re.search(r'2024年末[^。]{0,40}$', pre):
                if verbose:
                    print(f'    [提·跳过] {v} @ {m.start()} 年末累计 | {ctx}')
                continue
            # 优先级：模式序号越小越优先；再按出现位置
            cands.append((i, m.start(), v, ctx))
    if not cands:
        return None, None
    cands.sort(key=lambda x: (x[0], x[1]))
    best = cands[0]
    if verbose:
        for c in cands[:5]:
            print(f'    [提·候选] {c[2]} @ {c[1]} pat{c[0]} | {c[3]}')
    return _clean_num(best[2]), best[3]


def extract_loan(text, verbose=False):
    """返回 (value, context)。无有效候选返回 (None, None)。"""
    cands = []
    for i, p in enumerate(PAT_LOAN):
        for m in p.finditer(text):
            v = _num(m.group(1))
            if v is None or v <= 0:
                continue
            ctx = _window(text, m.start())
            if _is_bad(text, m.start(), len(m.group(0))):
                if verbose:
                    print(f'    [贷·跳过] {v} @ {m.start()} 否定词 | {ctx}')
                continue
            pre = text[max(0, m.start() - 60):m.start()]
            if re.search(r'(?:2024|2023)年末[^。]{0,40}$', pre):
                if verbose:
                    print(f'    [贷·跳过] {v} @ {m.start()} 年末累计 | {ctx}')
                continue
            cands.append((i, m.start(), v, ctx))
    if not cands:
        return None, None
    # 同一模式内，取位置最靠前的
    cands.sort(key=lambda x: (x[0], x[1]))
    best = cands[0]
    if verbose:
        for c in cands[:6]:
            print(f'    [贷·候选] {c[2]} @ {c[1]} pat{c[0]} | {c[3]}')
    return _clean_num(best[2]), best[3]


def yoy(cur, base):
    """同比 (cur-base)/base。"""
    if base is None or base == 0 or cur is None:
        return None
    return round((cur - base) / base * 100, 2)


def parse(text, verbose=False):
    w, wc = extract_withdraw(text, verbose)
    l, lc = extract_loan(text, verbose)
    return {'withdraw': w, 'withdraw_ctx': wc, 'loan': l, 'loan_ctx': lc}


if __name__ == '__main__':
    t = """2024年，提取额1693.90亿元，同比增长12.3%。
2024年，发放个人住房贷款10.90万笔951.23亿元，同比分别下降1.05%、增长14.27%。
2024年末，累计发放个人住房贷款333.05万笔13535.24亿元，贷款余额6191.94亿元。
2.异地贷款：2024年，发放异地贷款1066笔12.50亿元。
3.住房公积金贴息贷款：2024年，未发放住房公积金贴息贷款。"""
    print(parse(t, verbose=True))
