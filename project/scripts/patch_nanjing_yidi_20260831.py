#!/usr/bin/env python3
"""2026-08-31 南京公积金异地贷款扩至全国（宁金管规〔2026〕3号）入库"""
import json

NOTICE_URL = "https://gjj.nanjing.gov.cn/zwgk/tzgg/202608/t20260829_5901929.html"
GOV_PAGE_URL = "https://www.nanjing.gov.cn/bmdt/202608/t20260831_5902461.html"

NEW_NOTE_HEAD = (
    "2026-08-29南京住房公积金管理中心发布宁金管规〔2026〕3号《关于进一步扩大住房公积金异地贷款范围的通知》"
    "（2026-09-01起施行）：住房公积金异地贷款范围扩展至全国，全国范围内的住房公积金缴存人在南京市购房均可向南京公积金中心申请住房公积金贷款。"
    "解读要点（南京日报/南京市政府门户）：①为南京异地贷款范围2024年5月以来第四次调整——2024-05南京都市圈九城互认互贷互提、2025-07江苏全域（二手房贷款最长期限20年延至30年）、"
    "2026-04安徽全域（苏皖29城）、本次扩至全国，彻底打破行政地域壁垒；②受益群体为因工作、求学、落户等有意来宁购房的外地缴存职工及跨城就业的新市民、青年人；"
    "③作用三层面：降低购房融资成本（公积金利率低于商贷）、提高公积金使用效率（唤醒\"沉睡\"账户）、便利跨城就业群体；"
    "④成效数据：2024-05扩容以来已发放异地贷款2800多笔、金额超23亿元；⑤办理渠道：12329公积金服务热线、各业务承办银行网点。"
)

CONDITIONS_APPEND = (
    "；异地贷款（宁金管规〔2026〕3号，2026-09-01起）：全国范围内的住房公积金缴存人在南京市购房均可申请"
)

SOURCES_NEW = [
    {
        "title": "关于进一步扩大住房公积金异地贷款范围的通知（宁金管规〔2026〕3号，南京住房公积金管理中心）",
        "url": NOTICE_URL,
        "date": "2026-08-29",
    },
    {
        "title": "南京公积金异地贷款扩至全国（南京市政府门户·南京日报，含政策沿革与专家解读）",
        "url": GOV_PAGE_URL,
        "date": "2026-08-31",
    },
]


def update(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    nj = next(c for c in d["cities"] if c["city"] == "南京")
    nj["last_updated"] = "2026-08-31"
    # loan.conditions 追加异地贷款条款
    cond = nj["loan"]["conditions"]
    if "异地贷款" not in cond:
        nj["loan"]["conditions"] = cond + CONDITIONS_APPEND
    # loan.note 前插新政及解读
    note = nj["loan"]["note"]
    if "宁金管规〔2026〕3号" not in note:
        nj["loan"]["note"] = NEW_NOTE_HEAD + "｜" + note
    # sources 去重后置顶新增
    existing_urls = {s["url"] for s in nj["loan"]["sources"]}
    for s in reversed(SOURCES_NEW):
        if s["url"] not in existing_urls:
            nj["loan"]["sources"].insert(0, s)
    # 版本号与生成时间
    d["version"] = "1.4.4"
    d["generated_at"] = "2026-08-31"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(f"{path}: version={d['version']} nanjing.last_updated={nj['last_updated']} "
          f"sources={len(nj['loan']['sources'])}")


update("/Users/xuyixuan/gjj-policy-watch/gjj_policy_database.json")
update("/Users/xuyixuan/gjj-policy-watch/app/db.json")
