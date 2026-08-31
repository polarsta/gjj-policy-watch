#!/usr/bin/env python3
"""2026-08-31 依据 updated_cities_sources.md 核验结果，更新 data/merged_gjj_policy_database.json 29城缴存基数上下限"""
import json

# (城市, 核验后上限或None(不变), 核验后下限或None(不变))；None 表示 MD 中为原值或"—"，不修改
UPDATES = [
    ("北京",     36348,   None),
    ("南宁",     35283,   None),
    ("南通",     None,    2660),
    ("泰州",     None,    2660),
    ("湖州",     31436,   2430),
    ("六安",     25945,   None),
    ("南昌",     None,    2600),
    ("宜昌",     26714.50, 1970),
    ("黄石",     25291,   2130),
    ("洛阳",     23914,   2350),
    ("安阳",     19903,   2350),
    ("泸州",     26601,   2200),
    ("曲靖",     25893,   2020),
    ("丽江",     28746,   1920),
    ("红河州",   27016,   2020),
    ("贵阳",     25980,   None),
    ("遵义",     24405,   None),
    ("银川",     None,    2235),
    ("吕梁",     24733,   None),
    ("朔州",     25044,   None),
    ("吉林市",   22734.75, None),
    ("通化",     19816,   None),
    ("哈尔滨",   28430,   None),
    ("大庆",     32701,   None),
    ("锦州",     21945,   None),
    ("丹东",     22141,   None),
    ("日照",     26484,   2210),
    ("滨州",     None,    2020),
    ("龙岩",     28559,   None),
]

PATH = "/Users/xuyixuan/gjj-policy-watch/data/merged_gjj_policy_database.json"

with open(PATH, encoding="utf-8") as f:
    d = json.load(f)

changed = []
for city, new_upper, new_lower in UPDATES:
    c = next(x for x in d["cities"] if x["city"] == city)
    old_u, old_l = c["deposit"].get("base_upper"), c["deposit"].get("base_lower")
    touched = False
    if new_upper is not None and new_upper != old_u:
        c["deposit"]["base_upper"] = new_upper
        touched = True
    if new_lower is not None and new_lower != old_l:
        c["deposit"]["base_lower"] = new_lower
        touched = True
    if touched:
        c["last_updated"] = "2026-08-31"
        changed.append((city, old_u, new_upper, old_l, new_lower))

d["meta"]["generated_at"] = "2026-08-31 23:52:00"
d["meta"]["last_change"] = "2026-08-31 缴存基数上下限核验更新：29城（依据官方来源核验，详见 updated_cities_sources.md）"

with open(PATH, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

print(f"{'城市':<6}{'上限(旧→新)':<22}{'下限(旧→新)':<18}")
for city, ou, nu, ol, nl in changed:
    fu = f"{ou}→{nu}" if nu is not None else "-"
    fl = f"{ol}→{nl}" if nl is not None else "-"
    print(f"{city:<6}{fu:<22}{fl:<18}")
print(f"\n共更新 {len(changed)}/29 城")
