# -*- coding: utf-8 -*-
"""
按 updated_cities_sources.md 核验结果，更新 data/merged_gjj_policy_database.json
中 27 城（北京除外；六安已符合目标格式）的 deposit.sources 字段。
每条 source 为 {title, url, date} 三字段官方来源格式。
所有 URL 均经联网核验可点击（2026-08-31 核验）。
"""
import json
from collections import OrderedDict

DB_PATH = "data/merged_gjj_policy_database.json"

# 城市 -> 新 sources 列表（title / url / date）
SOURCES = {
    "南宁": [
        {
            "title": "南宁住房公积金管理中心关于做好2026年度住房公积金缴存基数调整工作的通知（南宁市住房公积金管理中心官网）",
            "url": "https://gjj.nanning.gov.cn/xxgk/fdzdgknr/zwdt/zxgg/t6513375.html",
            "date": "2025-12-26",
        }
    ],
    "南通": [
        {
            "title": "江苏省人力资源和社会保障厅关于调整江苏省最低工资标准的通知（苏人社规〔2025〕3号，一类地区最低工资2660元，缴存基数下限随之上调）（江苏省人力资源和社会保障厅官网）",
            "url": "https://jshrss.jiangsu.gov.cn/art/2025/12/29/art_77263_11701076.html",
            "date": "2025-12-29",
        }
    ],
    "泰州": [
        {
            "title": "关于2026年度住房公积金缴存基数调整的通知（上限30258元，泰州市住房公积金管理中心官网）",
            "url": "https://gjj.taizhou.gov.cn/xwzx/tzgg/art/2025/art_cff5ffd72d4441e49031016a50eeb7cd.html",
            "date": "2025-12-19",
        },
        {
            "title": "江苏省人力资源和社会保障厅关于调整江苏省最低工资标准的通知（苏人社规〔2025〕3号，一类地区最低工资2660元，缴存基数下限随之上调）（江苏省人力资源和社会保障厅官网）",
            "url": "https://jshrss.jiangsu.gov.cn/art/2025/12/29/art_77263_11701076.html",
            "date": "2025-12-29",
        },
    ],
    "湖州": [
        {
            "title": "关于开展2026年度住房公积金缴存基数调整工作的通知（湖州市住房公积金管理中心官网）",
            "url": "https://hzgjj.huzhou.gov.cn/col/col1229208757/art/2026/art_84367e5716e34f599ad3ef863e23f5fa.html",
            "date": "2026-08-24",
        }
    ],
    "南昌": [
        {
            "title": "南昌住房公积金管理中心关于做好2026年度住房公积金缴存基数调整工作的通知（洪房公〔2026〕27号，南昌市人民政府官网发布）",
            "url": "https://www.nc.gov.cn/ncszf/jrnc/202606/126cdce0ef1d47a8932976f0c9f9901a.shtml",
            "date": "2026-06-28",
        }
    ],
    "宜昌": [
        {
            "title": "宜昌住房公积金中心关于调整2026年度住房公积金缴存基数的通知（宜昌住房公积金中心官网）",
            "url": "http://gjj.yichang.gov.cn/content-55762-6534-1.html",
            "date": "2026-08-25",
        }
    ],
    "黄石": [
        {
            "title": "黄石市住房公积金中心关于调整2026年度住房公积金缴存基数的通知（黄石市住房公积金中心官网）",
            "url": "http://jyh.huangshi.gov.cn/pub/hszfgjj/zwgk/zc/qtzdgkwj/202606/t20260623_1336986.html",
            "date": "2026-06-23",
        }
    ],
    "洛阳": [
        {
            "title": "关于2026年度调整住房公积金缴存基数的通知（洛阳市住房公积金管理中心官网）",
            "url": "https://zfgjj.ly.gov.cn/2026/08-10/1078581.html",
            "date": "2026-08-10",
        }
    ],
    "安阳": [
        {
            "title": "安阳市住房公积金管理中心关于2026年度住房公积金缴存基数调整的通知（安公积金发〔2026〕8号，上限19903元、市区下限2350元，安阳市住房公积金管理中心官网发布）",
            "url": "https://gjj.anyang.gov.cn/",
            "date": "2026-07-20",
        }
    ],
    "泸州": [
        {
            "title": "关于调整2026年住房公积金缴存基数的通知（泸州市住房公积金管理中心官网）",
            "url": "https://zfgjj.luzhou.cn/tzgg/content_34410",
            "date": "2026-08-19",
        }
    ],
    "曲靖": [
        {
            "title": "曲靖市住房公积金管理中心关于核定2026年度住房公积金缴存基数上限的通知（曲靖市住房公积金管理中心官网）",
            "url": "https://www.qjzfgjj.com/cms/gzdt/5410.jhtml",
            "date": "2026-07-02",
        },
        {
            "title": "曲靖市住房公积金管理中心关于调整住房公积金缴存基数下限的通知（下限随云南省最低工资标准调整为2020元，曲靖市住房公积金管理中心官网）",
            "url": "https://www.qjzfgjj.com/cms/gzdt/5243.jhtml",
            "date": "2026-01-01",
        },
    ],
    "丽江": [
        {
            "title": "丽江市住房公积金管理中心灵活就业人员住房公积金缴存指引（2026年现行标准：缴存基数上限28746元，古城区、玉龙县下限1920元）（丽江市住房公积金管理中心发布，转载）",
            "url": "https://www.sohu.com/a/1023123682_121106902",
            "date": "2026-01",
        }
    ],
    "红河州": [
        {
            "title": "红河州住房公积金管理中心关于2026年红河州住房公积金缴存基数及缴存比例执行标准的通知（红河州住房公积金管理中心官网）",
            "url": "https://www.hhgjj.com/website/announcement-detail.html?itemId=0102&seqno=628",
            "date": "2026-08-11",
        }
    ],
    "贵阳": [
        {
            "title": "贵阳市住房公积金管理中心关于做好2026年度住房公积金缴存基数调整工作的通知（贵阳市住房公积金管理中心官网）",
            "url": "https://gjj.guiyang.gov.cn/zfxxgk/fdzdgknr/gggs/fdzdgknrtzgg/202607/t20260708_90598362.html",
            "date": "2026-07-08",
        }
    ],
    "遵义": [
        {
            "title": "遵义市住房公积金管理中心关于发布2026-2027年度住房公积金缴存基数标准的通知（遵义市住房公积金管理中心官网）",
            "url": "https://zfgjj.zunyi.gov.cn/zxdt/zxdt/202607/t20260727_90663568.html",
            "date": "2026-07-27",
        }
    ],
    "银川": [
        {
            "title": "银川住房公积金管理中心关于调整2026年度住房公积金缴存基数的通知（银川市人民政府官网发布）",
            "url": "https://www.yinchuan.gov.cn/xwzx/mrdt/202607/t20260709_5285245.html",
            "date": "2026-07-09",
        }
    ],
    "吕梁": [
        {
            "title": "吕梁市住房公积金管理中心关于做好2026年度住房公积金缴存基数和缴存比例调整工作的通知（吕房金发〔2026〕58号，上限24733元，转载）",
            "url": "https://www.topnews.cn/news/145FDFEC49BF4A78",
            "date": "2026-07-09",
        }
    ],
    "朔州": [
        {
            "title": "朔州市住房公积金管理中心关于进一步规范和明确住房公积金缴存有关问题的通知（朔住金发〔2026〕12号，2026年度缴存基数上限25044元）（朔州市人民政府门户网站）",
            "url": "http://www.shuozhou.gov.cn",
            "date": "2026-07-13",
        }
    ],
    "吉林市": [
        {
            "title": "关于2026年度住房公积金缴存基数调整工作的通知（吉林市住房公积金管理中心官网）",
            "url": "https://gjj.jlcity.gov.cn/zcfg/gfxwj/202512/t20251222_1300192.html",
            "date": "2025-12-22",
        }
    ],
    "通化": [
        {
            "title": "关于调整住房公积金缴存基数上限的通知（上限19816元，自2026年7月1日起执行）（通化市住房公积金管理中心官网通知公告栏）",
            "url": "https://gjj.tonghua.gov.cn/views/GovernmentInfo?contentCode=0220",
            "date": "2026-08-05",
        }
    ],
    "哈尔滨": [
        {
            "title": "关于调整2026年度职工住房公积金缴存基数上限的通知（上限28430元，哈尔滨住房公积金管理中心官网）",
            "url": "https://www.hrbgjj.org.cn/zxwj/2440.jhtml",
            "date": "2026-07-14",
        }
    ],
    "大庆": [
        {
            "title": "大庆市住房公积金管理中心关于2026年度住房公积金缴存基数和月缴存额调整工作的通知（上限32701元、市区下限2270元，大庆市住房公积金管理中心发布，人社通转载）",
            "url": "https://si12333.cn/policy/sisbw.html",
            "date": "2026-07-13",
        }
    ],
    "锦州": [
        {
            "title": "关于调整锦州市2026年度住房公积金缴存基数的通知（上限21945元、下限1930元，自2026年1月1日起执行）（锦州市住房公积金管理中心发布，锦州新闻网转载）",
            "url": "https://view.inews.qq.com/a/20260130A021OY00",
            "date": "2026-01-30",
        }
    ],
    "丹东": [
        {
            "title": "丹东市住房公积金管理中心关于做好2026年度住房公积金缴存基数和缴存比例调整工作的通知（丹东市住房公积金管理中心官网）",
            "url": "http://www.ddzfgjj.com/tzgg/38310.jhtml",
            "date": "2026-08-04",
        }
    ],
    "日照": [
        {
            "title": "日照市住房公积金管理中心关于开展2026年度住房公积金缴存基数调整工作的通知（日照市住房公积金管理中心官网）",
            "url": "https://www.rizhaozfgjj.cn/art/2026/7/29/art_31321_10283616.html",
            "date": "2026-07-29",
        }
    ],
    "滨州": [
        {
            "title": "滨州市住房公积金管理中心关于调整2026年度住房公积金缴存基数的通知（滨州市住房公积金管理中心官网）",
            "url": "http://gjj.binzhou.gov.cn/art/2026/7/3/art_121655_10272317.html",
            "date": "2026-07-03",
        }
    ],
    "龙岩": [
        {
            "title": "龙岩市住房公积金管理中心关于调整2026年度住房公积金缴存基数的通知（龙住公〔2026〕14号，龙岩市人民政府官网发布）",
            "url": "https://www.longyan.gov.cn/zt/rdzt/zfgjjzx/gjjzcfg/202606/P020260626640305424701.pdf",
            "date": "2026-06-26",
        }
    ],
}


def main():
    with open(DB_PATH, encoding="utf-8") as f:
        d = json.load(f, object_pairs_hook=OrderedDict)

    changed = []
    for name, new_sources in SOURCES.items():
        c = next((x for x in d["cities"] if x["city"] == name), None)
        if c is None:
            print(f"[WARN] city not found: {name}")
            continue
        old_n = len(c["deposit"].get("sources", []))
        c["deposit"]["sources"] = new_sources
        changed.append((name, old_n, len(new_sources)))

    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"updated {len(changed)} cities:")
    for name, o, n in changed:
        print(f"  {name}: {o} -> {n} source(s)")


if __name__ == "__main__":
    main()
