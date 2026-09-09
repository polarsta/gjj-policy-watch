#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
personnel-changes.json 批次追加补丁：2026-08-27 ~ 2026-09-09

口径（经用户确认）：
  1) 累积追加——保留 2026-06-26~08-26 已有记录，新记录追加进同一数组并打 batch 标记
  2) 仅收录「中心领导班子正副职」（主任/副主任/党组书记/党组成员/总会计师）
     不收中层干部、非领导职务、分管市领导；口径外线索留存 pending_verification

为什么用文本级手术而非 json.dump：
  原文件 persons / suspect_names 为内联数组，no_change_cities 为 10 项/行折行，
  json.dump(indent=2) 会把它们全部展开成一项一行，diff 从几十行炸到上千行。
  本脚本只做纯追加 + no_change_cities 摘除，不触碰任何已有条目。

用法：
  python3 patch_personnel_20260909.py            # dry-run，只打印 diff 摘要
  python3 patch_personnel_20260909.py --apply    # 落盘（含 site/ 镜像）
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "research" / "personnel-changes.json"
MIRROR = ROOT / "site" / "research" / "personnel-changes.json"

BATCH = "2026-08-27~2026-09-09"

# ---------------------------------------------------------------- 新增条目
NEW_CONFIRMED = [
    {
        "city": "遵义",
        "date": "2026-08-31",
        "decision_date": "2026-08-28",
        "category": "领导班子",
        "act": "new",
        "persons": ["罗红强", "艾明勇"],
        "content": "中心副主任任免：罗红强任遵义市住房公积金管理中心副主任（不再担任市国防动员办公室／市人民防空办公室副主任），艾明勇不再担任中心副主任职务（遵府任〔2026〕40号，决定日 08-28，发布日 08-31）",
        "source_tier": 1,
        "source_name": "遵义市人民政府",
        "url": "https://www.zunyi.gov.cn/zwgk/zfwj/zfr/202608/t20260831_90797819.html",
        "batch": BATCH,
    },
    {
        "city": "咸阳",
        "date": "2026-09-02",
        "decision_date": "2026-08-28",
        "category": "领导班子",
        "act": "removed",
        "persons": ["余龙彦"],
        "content": "免去余龙彦咸阳市住房公积金管理中心副主任职务（咸政任字〔2026〕35号，决定日 08-28，公开日 09-02）；同批文件未公布接任人选",
        "source_tier": 1,
        "source_name": "咸阳市人民政府",
        "url": "https://www.xianyang.gov.cn/zfxxgk/zcwj/rsrm/202609/t20260902_2113387.html",
        "batch": BATCH,
    },
    {
        "city": "乐山",
        "date": "2026-09-04",
        "category": "领导班子",
        "act": "pending",
        "persons": ["王颜兰"],
        "content": "任前公示：现任市财政局党组成员、市住房公积金管理中心主任王颜兰拟调任正县级领导职务（乐山市委组织部 09-04 发布，公示期 09-07 至 09-11）。若正式调任，中心主任一职将出现空缺",
        "source_tier": 1,
        "source_name": "人民网四川频道（转乐山市委组织部干部任前公示）",
        "url": "https://sc.people.com.cn/n2/2026/0907/c345514-41689065.html",
        "batch": BATCH,
    },
]

NEW_PENDING = [
    {
        "city": "六盘水",
        "date": "2026-09-09",
        "status": "非任免",
        "persons": ["袁怀祥", "粟建良", "牟钢", "蒙元芳", "黄梅"],
        "content": "中心党组发布《关于中心班子成员及县级干部分工的通知》（非任免公告）：袁怀祥主持中心党组全面工作，粟建良、牟钢、蒙元芳分工调整，黄梅协助党组书记分管内部稽核审计。其中黄梅未见于此前公开的班子名单，疑为新增班子成员或县级干部，待官方任免文件确认",
        "source_tier": 1,
        "source_name": "六盘水市住房公积金管理中心",
        "url": "https://gjj.gzlps.gov.cn/yqgg/202609/t20260909_90850810.html",
        "batch": BATCH,
    },
    {
        "city": "六安",
        "date": "2026-09-08",
        "status": "口径外·中层干部",
        "persons": ["朱军"],
        "content": "市住房公积金中心市直管理部副主任朱军涉嫌严重违法，经六安市监委指定管辖，正接受金安区监委监察调查。属中层干部，未纳入本批次「中心班子正副职」收录口径，仅作留存备查",
        "source_tier": 1,
        "source_name": "六安纪检监察网",
        "url": "https://www.lajjjc.gov.cn/xxgk/scdc/zjsc/8948789.html",
        "batch": BATCH,
    },
]

# 本批次确认有变动 / 有监测事件，需从「无变动城市」名单摘除
DROP_FROM_NO_CHANGE = ["遵义", "咸阳", "乐山", "六安"]

BATCHES_BLOCK = """  "batches": [
    {
      "batch": "2026-06-26~2026-08-26",
      "window_start": "2026-06-26",
      "window_end": "2026-08-26",
      "generated": "2026-08-26",
      "scope": "中心领导班子 + 中层干部 + 非领导职务 + 分管市领导（四类全收并分组存放）",
      "method": "134 城分 10 批并行检索（WebSearch，时间过滤近 2 个月）",
      "confirmed_added": 11,
      "note": "本批次条目未标注 batch 字段；各数组内无 batch 字段的条目均属本批次"
    },
    {
      "batch": "2026-08-27~2026-09-09",
      "window_start": "2026-08-27",
      "window_end": "2026-09-09",
      "generated": "2026-09-09",
      "scope": "仅中心领导班子正副职（主任／副主任／党组书记／党组成员／总会计师）；不收中层干部、非领导职务与分管市领导",
      "method": "WebSearch 近 14 天时间过滤，按「任免／免去／任命／任前公示／纪律处分／监察调查／班子分工」等措辞 × 分省区域多轮交叉检索；命中条目逐条回源抓取正文，核对人名、职务、发文日期与文号，并实测链接 HTTP 200",
      "confirmed_added": 3,
      "note": "口径收窄经用户确认。口径外线索（中层干部监察调查、非任免类班子分工公告）留存于 pending_verification，未进 confirmed_changes"
    }
  ],
"""


def render_entry(obj: dict, indent: int = 4) -> str:
    """按原文件风格序列化单条记录：缩进 4，persons 内联。"""
    pad = " " * indent
    inner = " " * (indent + 2)
    lines = [pad + "{"]
    keys = list(obj.keys())
    for i, k in enumerate(keys):
        v = obj[k]
        if isinstance(v, list):
            body = "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in v) + "]"
        else:
            body = json.dumps(v, ensure_ascii=False)
        comma = "" if i == len(keys) - 1 else ","
        lines.append(f"{inner}{json.dumps(k, ensure_ascii=False)}: {body}{comma}")
    lines.append(pad + "}")
    return "\n".join(lines)


def wrap_city_list(cities, per_line=10, indent=4) -> str:
    pad = " " * indent
    rows = []
    for i in range(0, len(cities), per_line):
        chunk = cities[i:i + per_line]
        rows.append(pad + ", ".join(json.dumps(c, ensure_ascii=False) for c in chunk))
    return ",\n".join(rows)


def patch(txt: str) -> str:
    orig = txt

    # ---- 1. meta：window_end / generated / description / methodology / schema_version + batches
    txt = txt.replace(
        '"description": "近 2 个月、134 个城市住房公积金中心领导人事变动的公开信息汇总，作为可检索的信息源。",',
        '"description": "134 个城市住房公积金中心领导人事变动的公开信息汇总，作为可检索的信息源。数据按批次累积追加，统计窗口自 2026-06-26 起持续延伸；各批次口径见 meta.batches。",',
        1,
    )
    txt = txt.replace('"window_end": "2026-08-26",', '"window_end": "2026-09-09",', 1)
    txt = txt.replace('"generated": "2026-08-26",', '"generated": "2026-09-09",', 1)
    txt = txt.replace(
        '"methodology": "将 134 城分 10 批并行检索（WebSearch，时间过滤近 2 个月），逐条甄别来源层级与窗口边界，剔除跨城重复的聚合模板噪声，仅保留可核实的真实链接。",',
        '"methodology": "分批次滚动检索：每批对 134 城做多轮措辞 × 区域交叉检索，逐条甄别来源层级与窗口边界，回源核对正文与发文日期，剔除跨城重复的聚合模板噪声，仅保留可核实的真实链接。各批次的时间窗口、收录口径与检索方法见 meta.batches。",',
        1,
    )
    txt = txt.replace('"schema_version": "1.0",', '"schema_version": "1.1",', 1)

    # batches 插在 schema_version 之前。BATCHES_BLOCK 以 2 空格为基准书写，
    # meta 内的键实际缩进 4 格，故整块统一右移 2 格。
    assert '"batches"' not in txt, "batches 字段已存在，勿重复执行"
    block = "\n".join(("  " + ln) if ln.strip() else ln
                      for ln in BATCHES_BLOCK.rstrip("\n").split("\n")) + "\n"
    txt = txt.replace('    "schema_version": "1.1",',
                      block + '    "schema_version": "1.1",', 1)

    # ---- 2. confirmed_changes 追加
    a1 = '    }\n  ],\n  "supervising_city_leaders": ['
    assert txt.count(a1) == 1, "confirmed_changes 锚点不唯一"
    add1 = ",\n" + ",\n".join(render_entry(e) for e in NEW_CONFIRMED)
    txt = txt.replace(a1, "    }" + add1 + '\n  ],\n  "supervising_city_leaders": [', 1)

    # ---- 3. pending_verification 追加
    a2 = '    }\n  ],\n  "excluded_noise": {'
    assert txt.count(a2) == 1, "pending_verification 锚点不唯一"
    add2 = ",\n" + ",\n".join(render_entry(e) for e in NEW_PENDING)
    txt = txt.replace(a2, "    }" + add2 + '\n  ],\n  "excluded_noise": {', 1)

    # ---- 4. no_change_cities 摘除本批次有变动的城市
    m = re.search(r'(  "no_change_cities": \[\n)(.*?)(\n  \]\n?\})', txt, re.S)
    assert m, "no_change_cities 块未匹配"
    cities = json.loads("[" + m.group(2).replace("\n", " ") + "]")
    before = len(cities)
    kept = [c for c in cities if c not in DROP_FROM_NO_CHANGE]
    dropped = [c for c in cities if c in DROP_FROM_NO_CHANGE]
    txt = txt[:m.start(2)] + wrap_city_list(kept) + txt[m.end(2):]

    print(f"  no_change_cities: {before} -> {len(kept)}  摘除 {dropped}")
    assert txt != orig, "补丁未产生任何改动"
    return txt


def main():
    apply = "--apply" in sys.argv
    raw = MAIN.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "主文件意外带 BOM"
    txt = raw.decode("utf-8")
    had_eof_nl = txt.endswith("\n")

    new = patch(txt)

    # 结构校验
    data = json.loads(new)
    assert len(data["confirmed_changes"]) == 14, len(data["confirmed_changes"])
    assert len(data["pending_verification"]) == 8, len(data["pending_verification"])
    assert len(data["supervising_city_leaders"]) == 5
    assert data["meta"]["window_end"] == "2026-09-09"
    assert data["meta"]["generated"] == "2026-09-09"
    assert len(data["meta"]["batches"]) == 2
    assert data["meta"]["city_count"] == 134

    # 覆盖城市去重后 + 无变动城市 应等于 134
    touched = set()
    for k in ("confirmed_changes", "supervising_city_leaders", "pending_verification"):
        touched |= {e["city"] for e in data[k]}
    total = len(touched | set(data["no_change_cities"]))
    print(f"  覆盖校验：涉及变动/待核实 {len(touched)} 城 + 无变动 {len(data['no_change_cities'])} 城 = {total} 城")
    assert total == 134, f"城市合计 {total} != 134"
    assert not (touched & set(data["no_change_cities"])), "城市同时出现在变动名单与无变动名单"

    # 新条目前端分类自检（复刻 site/app.js leaderAct 规则）
    def leader_act(g):
        c, t = g.get("category", ""), g.get("content", "")
        if re.search(r"拟任|任前公示", t):
            return "pending"
        if c == "中层干部":
            return "mid"
        if c == "非领导职务":
            return "staff"
        if re.search(r"开除党籍|双开", t) or ("免" in t and "任" not in t):
            return "removed"
        return "new"

    print("  前端分类自检（当前 app.js 推断 vs 数据 act 字段）：")
    for e in data["confirmed_changes"]:
        if e.get("batch") != BATCH:
            continue
        inferred, declared = leader_act(e), e.get("act")
        flag = "OK " if inferred == declared else "!! 不一致"
        print(f"    {flag} {e['city']}: 推断={inferred} 声明={declared}")

    if not had_eof_nl:
        new = new.rstrip("\n")
    elif not new.endswith("\n"):
        new += "\n"

    if not apply:
        print("\n  [dry-run] 未落盘。加 --apply 生效。")
        return

    shutil.copy2(MAIN, MAIN.with_suffix(".json.bak_20260909"))
    MAIN.write_text(new, encoding="utf-8", newline="\n")
    MIRROR.write_text(new, encoding="utf-8", newline="\n")
    print(f"\n  已写入 {MAIN}")
    print(f"  已同步 {MIRROR}")
    r = subprocess.run(["git", "diff", "--stat", "HEAD", "--", "research/personnel-changes.json"],
                       cwd=ROOT, capture_output=True, text=True)
    print("  " + (r.stdout.strip() or "(git diff 无输出)"))


if __name__ == "__main__":
    main()
