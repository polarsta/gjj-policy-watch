#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核验公积金年报链接有效性。

用法：
    python project/scripts/verify_annual_report_links.py [链接文件.json]

说明：
  - 政府站证书链常不完整，必须关闭 SSL 校验（verify=False）。
  - 政务 WAF 会拦截 HEAD 或非浏览器 UA，故先用 GET(HEAD->GET 回退) + 浏览器 UA。
  - 返回 412/403/405 等需人工复核（MANUAL），不得据此判定链接失效，更不得删条目或编造替代链接。
"""
import json
import ssl
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

OK = {200, 206}
MANUAL = {403, 405, 412, 429, 451}  # WAF / 反爬特征码，需人工核验


def check(url):
    if not url:
        return {"code": None, "status": "EMPTY", "err": ""}
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
                code = r.getcode()
                if method == "GET":
                    r.read(2048)
                if code in OK:
                    return {"code": code, "status": "OK", "err": ""}
                if code in MANUAL:
                    return {"code": code, "status": "MANUAL", "err": ""}
                return {"code": code, "status": "HTTP_%s" % code, "err": ""}
        except urllib.error.HTTPError as e:
            code = e.code
            if code in MANUAL:
                return {"code": code, "status": "MANUAL", "err": ""}
            if method == "HEAD":
                continue  # 部分站点不支持 HEAD，回退 GET
            return {"code": code, "status": "HTTP_%s" % code, "err": ""}
        except Exception as e:
            if method == "HEAD":
                continue
            return {"code": None, "status": "ERR", "err": type(e).__name__ + ": " + str(e)[:80]}
    return {"code": None, "status": "ERR", "err": "all methods failed"}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "project/data/annual_report_links_40cities.json"
    items = json.load(open(path, encoding="utf-8-sig"))
    targets = [(it["city"], it["year"], it["url"]) for it in items if it.get("url")]

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda t: check(t[2]), targets))

    out = []
    for (city, year, url), res in zip(targets, results):
        rec = {"city": city, "year": year, "url": url}
        rec.update(res)
        out.append(rec)
        print("%-8s %s  %-8s %s %s" % (city, year, res["status"], res["code"] or "", res["err"]))

    dest = path.replace(".json", "_verify.json")
    json.dump(out, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    from collections import Counter
    print("\n汇总:", dict(Counter(r["status"] for r in out)))
    print("已写入:", dest)


if __name__ == "__main__":
    main()
