# -*- coding: utf-8 -*-
"""
导出 134 城住房公积金官网网址 -> CSV（UTF-8-SIG）

逻辑：
1. 优先取官方字段 cities[].official_site
2. 缺失的城市，从该城全部 sources[].url 中按规则推断公积金官网域名：
   优先含 gjj / zfgjj 且为 .gov.cn 或 .cn 的 host，其次含 gjj 的其他 host
3. 对每一条 URL 做真实可达性核验（政府站关闭 SSL 校验，并发 20）
4. 输出 CSV 到 data/out/ 与 ~/Downloads/
"""
import csv
import json
import os
import re
import ssl
import subprocess
import urllib.request
import urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(BASE, "gjj_policy_database.json")
OUT_DIR = os.path.join(BASE, "data", "out")
DOWNLOADS = os.path.expanduser("~/Downloads")
TODAY = "2026-09-03"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 人工查证结果（2026-09-03）：覆盖库内失效值 / 补录库中缺失值
# 格式: 城市 -> (url, 来源口径, 备注)
VERIFIED = {
    "江门": ("https://www.jiangmen.gov.cn/bmpd/jmszfhcxjsj/", "人工查证修正",
             "原 www.jiangmen.gov.cn/jmzjj 已 404；该市无独立公积金站，现指向市政府门户住建局栏目"),
    "衢州": ("https://www.qz.gov.cn/col/col1229709644/index.html", "人工查证修正",
             "原 gjjzx.qz.gov.cn 域名无法解析（2026-08 系统迁云）；现指向市政府门户公积金部门专栏"),
    "呼和浩特": ("https://www.hhhtgjj.org.cn", "人工查证修正",
                 "库值 http 版 302 跳转异常，改用 https 直达"),
    "鞍山": ("http://asgjj.anshan.gov.cn/", "人工查证修正",
             "该站仅支持 http，https 握手失败"),
    "滨州": ("http://gjj.binzhou.gov.cn/", "人工查证修正",
             "该站仅支持 http，https 握手失败；市政府机构职能页登记此址"),
    "漳州": ("http://gjj.zhangzhou.gov.cn/", "人工查证修正",
             "该站仅支持 http，https 握手失败；市政府声明此为唯一官网"),
    "大庆": ("https://daqing.gov.cn/daqing/c2025niandu5/202601/c05_401805.shtml", "用户指定补录",
             "该市无独立官网（dqgjj.cn 主站已无内容、SSL 失败）；用户指定市政府门户《大庆市住房公积金管理中心2025年政府信息公开工作年度报告》页，curl 核验 200"),
    # 库中缺失、人工补录
    "清远": ("http://gjjzx.gdqy.gov.cn/", "人工查证补录",
             "独立官网（gov.cn 子域），落地于市政府门户群栏目"),
    "宁波": ("https://zjw.ningbo.gov.cn/col/col1229126238/index.html", "人工查证补录",
             "无独立官网（gjj.ningbo.gov.cn 已无法解析），现为市住建局公积金政策专栏"),
    "孝感": ("http://xggjj.xiaogan.gov.cn/", "人工查证补录",
             "独立官网，仅 http 可达；政府信息公开指南自述此址为门户"),
    "衡阳": ("https://www.hengyang.gov.cn/hyszfgjj/", "人工查证补录",
             "无独立官网（旧 hysgjj.com 已弃用），为市政府门户公积金栏目；412 系 WAF 拦截"),
    "丽江": ("http://www.ljgjj.com/", "人工查证补录",
             "自办域名，市政府《2025年政府信息公开年报》明确为门户网站；403 系 WAF 拦截"),
    "朔州": ("http://www.zf365.com.cn/", "人工查证补录",
             "自办域名（晋ICP备11000586号-1），中心通告自述为官网；2026-09-03 17:00 核验 200，17:55 连续 3 次 502，属源站临时故障，链接保留待复检"),
    "龙岩": ("https://www.longyan.gov.cn/zt/rdzt/zfgjjzx/", "人工查证补录",
             "无独立官网（longyangjj.gov.cn 已无法解析），为市政府门户公积金中心专题"),
    "廊坊": ("https://lfzfgjj.net/website/index.html", "用户指定补录",
             "推断值 szgjj.hebei.gov.cn 是『河北省直住房资金中心』（省级，非廊坊市），已弃用；"
             "用户指定官网，curl 核验 200，页面标题『廊坊市住房公积金管理中心』"),
    # 第二轮抽查（2026-09-03）：6/6 全部正确，推断值含协议均无误，故直接入库
    "曲靖": ("https://www.qjzfgjj.com", "人工查证补录",
             "第二轮抽查确认；官方独立站，仅 https 可达（http 返 404）；曲靖市政府门户通知明确此址"),
    "西宁": ("https://www.xnzfgjj.com", "人工查证补录",
             "第二轮抽查确认；2026 年新版官网已迁至此域名，仅 https 可达"),
    "青岛": ("http://www.qdgjj.com", "人工查证补录",
             "第二轮抽查确认；http/https 双通，青岛政务网机构信息表登记 http 此址"),
    "安阳": ("https://gjj.anyang.gov.cn", "人工查证补录",
             "第二轮抽查确认；仅 https 可达；《政府网站工作年度报表》首页网址"),
    "六盘水": ("http://gjj.gzlps.gov.cn", "人工查证补录",
               "第二轮抽查确认；http/https 双通，市政府机构信息登记 http 此址"),
    "榆林": ("http://zfgjj.yl.gov.cn", "人工查证补录",
             "第二轮抽查确认；http/https 双通，市政府部门页及《政府网站工作年度报表》均列此址"),
}

# 省级行政区拼音（用于识别并降权「省直/省级」公积金站，避免把省级站当市级官网）
PROVINCE_KEYS = {
    "beijing", "tianjin", "shanghai", "chongqing", "hebei", "shanxi", "neimenggu",
    "liaoning", "jilin", "heilongjiang", "jiangsu", "zhejiang", "anhui", "fujian",
    "jiangxi", "shandong", "henan", "hubei", "hunan", "guangdong", "guangxi",
    "hainan", "sichuan", "guizhou", "yunnan", "xizang", "shaanxi", "gansu",
    "qinghai", "ningxia", "xinjiang",
}

# 已被确认为「非公积金官网」的通用域名黑名单（政府门户主站 / 热线 / 媒体 / 聚合站）
BLACKLIST_KEYWORDS = [
    "bendibao", "163.com", "sina", "sohu", "toutiao", "qq.com", "people",
    "chinanews", "m12333", "51shebao", "fangchan", "cnnb", "mohurd",
    "gov.cn/zhengce", "wzrb", "dqdaily", "qingcheng",
]


def load_db():
    with open(DB, encoding="utf-8-sig") as f:
        return json.load(f)


def iter_sources(obj):
    """深度遍历，yield 所有 url 字段"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "url" and isinstance(v, str):
                yield v
            else:
                yield from iter_sources(v)
    elif isinstance(obj, list):
        for i in obj:
            yield from iter_sources(i)


def host_of(url):
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1).lower() if m else None


def guess_official_site(city_obj):
    """从 sources 推断公积金官网，返回 (host_or_None, 命中次数)"""
    counter = Counter()
    for url in iter_sources(city_obj):
        h = host_of(url)
        if not h:
            continue
        if any(b in h for b in BLACKLIST_KEYWORDS):
            continue
        counter[h] += 1
    if not counter:
        return None, 0

    def score(h):
        bare = h[4:] if h.startswith("www.") else h   # 先剥离 www. 再判断域名主体
        s = 0
        if "zfgjj" in bare:
            s += 100
        elif "gjj" in bare:
            s += 80
        if h.endswith(".gov.cn"):
            s += 20
        elif h.endswith(".org.cn") or h.endswith(".cn"):
            s += 8
        elif h.endswith(".com"):
            s += 5
        if h.startswith("12345") or "12345" in h:
            s -= 200
        # 过于通用的省级/部门站点降权（如 zjj.jz.gov.cn 住建局、zjw.my.gov.cn）
        if h.count(".") == 3 and "gjj" not in bare:
            s -= 40
        if h.startswith("m."):
            s -= 50
        # 省级/省直公积金站不是市级官网（如 szgjj.hebei.gov.cn 是河北省直中心），重罚
        if any(seg in PROVINCE_KEYS for seg in bare.split(".")):
            s -= 150
        return s

    ranked = sorted(counter.items(), key=lambda kv: (-score(kv[0]), -kv[1], kv[0]))
    best, cnt = ranked[0]
    if score(best) < 60:
        return None, 0
    return best, cnt


def curl_check(url, timeout=20):
    """对 urllib 判定异常的链接用 curl 二次复检，排除 WAF / TLS 指纹导致的误判"""
    if not url:
        return "", "无链接"
    try:
        out = subprocess.run(
            ["curl", "-sS", "-o", "/dev/null", "-L", "-k", "--max-time", str(timeout),
             "-w", "%{http_code} %{url_effective}", "-A", UA,
             "-H", "Accept: text/html,application/xhtml+xml,*/*;q=0.8",
             "-H", "Accept-Language: zh-CN,zh;q=0.9",
             url],
            capture_output=True, text=True, timeout=timeout + 10)
        parts = out.stdout.strip().split(" ", 1)
        code = parts[0]
        eff = parts[1] if len(parts) > 1 else url
        if code == "200":
            return code, "可访问"
        if code in ("403", "412", "521", "502", "503", "429"):
            return code, "疑似WAF/反爬拦截（链接本身大概率有效，需人工确认）"
        if code == "404":
            return code, "链接失效(404)"
        return code or out.stderr.strip()[:40], "异常，需人工确认"
    except Exception as e:  # noqa
        return type(e).__name__, "无法访问"


def check_url(url, timeout=10):
    """返回 (状态码, 说明)。GET 优先，失败退 HEAD"""
    if not url:
        return "", "无链接"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    last = ""
    for method in ("GET", "HEAD"):
        try:
            req = urllib.request.Request(url, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return str(r.status), "可访问"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 404:
                return last, "链接失效(404)"
        except Exception as e:  # noqa
            last = type(e).__name__
            continue
    return last, "无法访问"


def main():
    db = load_db()
    cities = db["cities"]

    rows = []
    for c in cities:
        city = c.get("city", "")
        province = c.get("province", "")
        site = (c.get("official_site") or "").strip()
        if city in VERIFIED:
            # 人工查证结果优先级最高
            site, origin, note = VERIFIED[city]
        elif site:
            origin = "数据库字段 official_site"
            note = ""
        else:
            host, cnt = guess_official_site(c)
            if host:
                site = "https://" + host
                origin = "来源推断（sources 域名反推）"
                note = f"库中无 official_site；来源链接命中 {cnt} 次，待人工核验"
            else:
                site = ""
                origin = "缺失"
                note = "库中无 official_site，且来源中无公积金专属域名，待补录"
        rows.append({
            "序号": "",
            "城市": city,
            "省份": province,
            "公积金官网网址": site,
            "网址来源": origin,
            "链接核验": "",
            "核验说明": "",
            "数据最后更新日期": c.get("last_updated", ""),
            "备注": note,
        })

    # 并发核验（urllib 一轮，异常项用 curl 二次复检）
    def work(r):
        code, desc = check_url(r["公积金官网网址"])
        if code != "200":
            # 异常项用 curl 复检最多 2 次（并发下易抖动，单次失败不足以下结论）
            code2, desc2 = "", desc
            for _ in range(2):
                code2, desc2 = curl_check(r["公积金官网网址"])
                if code2 == "200":
                    break
            if code2 == "200":
                code, desc = code2, desc2
            else:
                code, desc = f"{code}/{code2}".strip("/"), desc2
        r["链接核验"] = code
        r["核验说明"] = desc
        return r

    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(work, rows))

    for i, r in enumerate(rows, 1):
        r["序号"] = i

    os.makedirs(OUT_DIR, exist_ok=True)
    fields = ["序号", "城市", "省份", "公积金官网网址", "网址来源",
              "链接核验", "核验说明", "数据最后更新日期", "备注"]
    fname = f"公积金134城官网网址清单_{TODAY.replace('-', '')}.csv"
    paths = [os.path.join(OUT_DIR, fname), os.path.join(DOWNLOADS, fname)]
    for p in paths:
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    # 统计
    total = len(rows)
    from_db = sum(1 for r in rows if r["网址来源"].startswith("数据库字段"))
    guessed = sum(1 for r in rows if r["网址来源"].startswith("来源推断"))
    verified = sum(1 for r in rows if r["网址来源"].startswith(("人工查证", "用户指定")))
    missing = sum(1 for r in rows if r["网址来源"] in ("缺失", "人工查证·证据不足"))
    ok = sum(1 for r in rows if r["链接核验"] == "200")
    print(f"总计 {total} 城 | 库字段 {from_db} | 来源推断 {guessed} | 人工查证/指定 {verified} | 缺失 {missing}")
    print(f"核验 200 可访问：{ok}，异常 {total - ok}")
    print("异常明细：")
    for r in rows:
        if r["链接核验"] != "200":
            print(f"  {r['城市']} | {r['公积金官网网址'] or '(空)'} | {r['链接核验']} | {r['核验说明']}")
    for p in paths:
        print("输出:", p)


if __name__ == "__main__":
    main()
