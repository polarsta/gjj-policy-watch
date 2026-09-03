#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 40 城公积金年报链接更新记录 Markdown。"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AP = os.path.join(ROOT, "project/data/annual_report_links_40cities_applied.json")
OUT = os.path.join(ROOT, "年报链接更新记录_20260903.md")

JUNK = ("m12333.cn", "si12333.cn", "zc.51shebao.com", "www.sohu.com",
        "m.sohu.com", "o546.cn", "news.fang.com")


def tag(u):
    """判断旧链接性质，用于说明这次替换的意义。"""
    if not u:
        return "空缺"
    for j in JUNK:
        if j in u:
            return {"m12333.cn": "占位", "si12333.cn": "占位",
                    "zc.51shebao.com": "聚合", "www.sohu.com": "聚合",
                    "m.sohu.com": "聚合", "o546.cn": "聚合",
                    "news.fang.com": "聚合"}[j]
    if "mp.weixin.qq.com" in u:
        return "政务新媒体"
    if ".gov.cn" in u or ".gov.cn:" in u:
        return "政府站"
    return "其他"


def main():
    ap = json.load(open(AP, encoding="utf-8"))
    db = json.loads(open(os.path.join(ROOT, "gjj_policy_database.json"),
                         encoding="utf-8-sig").read())
    changes = ap["changes"]
    unchanged = ap["unchanged"]

    L = []
    L.append("# 住房公积金年报链接更新记录（40 城）")
    L.append("")
    L.append("- **执行日期**：2026-09-03")
    L.append("- **数据源**：`更新40城链接.xlsx`（城市 / 2025年报链接 / 2024年报链接）")
    L.append("- **目标文件**：`gjj_policy_database.json` → `annual_reports.cities[].report_2025|report_2024.url`")
    L.append("- **备份**：`gjj_policy_database.json.bak_2026-09-03`")
    L.append("")

    L.append("## 一、结果概览")
    L.append("")
    L.append("| 项目 | 数量 | 说明 |")
    L.append("|---|---|---|")
    L.append("| 涉及城市 | 40 | 全部在数据库中匹配成功，无未匹配项 |")
    L.append("| 实际更新链接 | **47** | 已写入数据库 |")
    L.append("| 链接一致无需变更 | 21 | 库内链接与文档完全一致，保留 |")
    L.append("| 文档未提供链接 | 12 | 该城该年度文档留空，不改动库内原值 |")
    L.append("| 需人工复核 | 2 | 清远市政府站 JS 挑战，见第四节 |")
    L.append("| 已修正失效链接 | 1 | 襄阳 2024，见第三节 |")
    L.append("")
    L.append("被替换的 47 条旧链接按性质分布：")
    L.append("")
    dist = {}
    for c in changes:
        dist[tag(c["old"])] = dist.get(tag(c["old"]), 0) + 1
    L.append("| 旧链接性质 | 条数 |")
    L.append("|---|---|")
    for k, v in sorted(dist.items(), key=lambda x: -x[1]):
        L.append("| %s | %d |" % (k, v))
    L.append("")
    L.append("> 其中 `m12333.cn` / `si12333.cn` 的随机短路径并无真实内容，属历史遗留占位链接；"
             "`sohu` / `51shebao` / `fang.com` 为商业聚合转载。本次 47 条全部换为政府站或政务新媒体原出处。")
    L.append("")

    L.append("## 二、更新明细（47 条）")
    L.append("")
    L.append("| # | 城市 | 年度 | 旧链接性质 | 新链接 | 核验 |")
    L.append("|---|---|---|---|---|---|")
    for i, c in enumerate(changes, 1):
        L.append("| %d | %s | %d | %s | [%s](%s) | %s |" % (
            i, c["city"], c["year"], tag(c["old"]),
            re.sub(r"^https?://", "", c["new"])[:58] + ("…" if len(c["new"]) > 66 else ""),
            c["new"], c["status"]))
    L.append("")

    L.append("## 三、失效链接修正")
    L.append("")
    L.append("| 城市 | 年度 | 原状况 | 处置 |")
    L.append("|---|---|---|---|")
    L.append("| 襄阳 | 2024 | 文档与库内同为 "
             "`.../zwgk/gkml/ghjh/202505/t20250512_3808613.shtml`，实测 **404**，"
             "且路径落在「规划计划」栏目而非年报栏目 | 改取官方年报目录同名条目 "
             "[襄阳市住房公积金2024年年度报告]"
             "(http://gjj.xiangyang.gov.cn/zwgk/gknb/202503/t20250321_3781562.shtml)，"
             "页面标题已确认，HTTP 200 |")
    L.append("")
    L.append("> 说明：该链接是文档与数据库**同时**失效（属历史遗留问题，非本次引入）。"
             "修正链接取自 `gjj.xiangyang.gov.cn` 官方「公积金年报」栏目列表页，未编造。")
    L.append("")

    L.append("## 四、需人工复核（2 条）")
    L.append("")
    L.append("| 城市 | 年度 | 现象 | 建议 |")
    L.append("|---|---|---|---|")
    for c in changes:
        if c["status"] == "MANUAL":
            L.append("| %s | %d | 清远市政府站（www.gdqy.gov.cn）启用 JS 挑战（瑞数类 WAF），"
                     "自动化请求返回 %s，页面标题为「请稍候…」 | 用浏览器打开一次确认可正常渲染；"
                     "域名为清远市政府官方站，链接已按原文写入，未做删改 |"
                     % (c["city"], c["year"], "412" if c["year"] == 2025 else "405"))
    L.append("")
    L.append("> 按项目约定：政务 WAF 返回 412/403 属反爬特征而非链接失效，"
             "**不得**因自动化核验失败删除条目或替换成其他链接。")
    L.append("")

    L.append("## 五、文档未提供链接（12 条，保持原值未动）")
    L.append("")
    L.append("| 城市 | 年度 | 库内现有链接性质 |")
    L.append("|---|---|---|")
    def norm(s):
        return str(s or "").replace("市", "").replace(" ", "")
    n2c = {norm(c["city"]): c for c in db["annual_reports"]["cities"]}
    for city, yr, reason in unchanged:
        if "未提供" not in reason:
            continue
        cur = (n2c[norm(city)].get("report_%s" % yr) or {}).get("url")
        L.append("| %s | %d | %s |" % (city, yr, tag(cur)))
    L.append("")

    L.append("## 六、遗留待清理（13 条，不在本次 40 城范围内）")
    L.append("")
    L.append("全库扫描后，仍有 13 条年报链接指向占位/聚合来源，本次文档未覆盖，建议下一批补充：")
    L.append("")
    L.append("| 城市 | 年度 | 现有链接 | 性质 |")
    L.append("|---|---|---|---|")
    for c in db["annual_reports"]["cities"]:
        for yr in (2025, 2024):
            u = (c.get("report_%s" % yr) or {}).get("url") or ""
            if any(j in u for j in JUNK):
                L.append("| %s | %d | %s | %s |" % (c["city"], yr, u, tag(u)))
    L.append("")

    L.append("## 七、执行方式")
    L.append("")
    L.append("```bash")
    L.append("# 1) 核验链接（政府站关闭 SSL 校验，HEAD 失败回退 GET）")
    L.append("python project/scripts/verify_annual_report_links.py")
    L.append("")
    L.append("# 2) 写入数据库（先 dry-run，确认后加 --apply）")
    L.append("python project/scripts/apply_annual_report_links.py")
    L.append("python project/scripts/apply_annual_report_links.py --apply")
    L.append("")
    L.append("# 3) 同步到站点目录")
    L.append("cp gjj_policy_database.json site/gjj_policy_database.json")
    L.append("```")
    L.append("")
    L.append("中间产物：`project/data/annual_report_links_40cities[_verify|_applied].json`")
    L.append("")

    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("已生成:", OUT, len("\n".join(L)), "字符")


if __name__ == "__main__":
    main()
