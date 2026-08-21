# 公积金政策数据库定时更新方案

> 目标：对 134 个城市的公积金政策数据库（`gjj_policy_database.json`）实现每周/每日自动巡检，发现新增/变更政策后自动更新数据库并提醒。

---

## 一、政策变更的来源特征（先理解"更新从哪来"）

公积金政策的变更高度规律化，集中在三类触发点：

| 触发类型 | 频率 | 典型时间窗口 | 影响字段 |
|---|---|---|---|
| **年度缴存基数调整** | 每年1次 | 每年6-7月（多数城市7月1日起执行新年度基数上下限） | deposit.base_upper / base_lower / ratio |
| **贷款利率调整** | 不定期（跟随央行） | 央行下调 LPR 或公积金基准利率后（如2024年5月、2025年5月全国性下调） | loan.rate_first / rate_second |
| **阶段性优化政策** | 高频、随机 | 各地随楼市形势随时出台（提高额度、降低首付、放宽提取、多子女/人才上浮） | loan.max_* / down_payment_* / withdrawal.* |

**结论**：更新方案的核心不是"每天重采134城"，而是"低成本监测各城市公积金中心的**公告/通知栏目**，命中新政策后才做定向重采"。

---

## 二、信息源分层与监测清单

### 第1层：官方一手来源（必须监测，准确性最高）
- 各城市住房公积金管理中心官网的「通知公告 / 政策法规」栏目（数据库中每个城市的 `official_site` 字段即入口）
- 全国层面：住房和城乡建设部官网 (mohurd.gov.cn)、中国人民银行 (pbc.gov.cn) —— 利率类全国性调整由此首发

### 第2层：政府聚合平台（补充）
- 各省政府官网"政策文件"栏目、政务服务网（如"浙里办""粤省事"公告页）
- 国家政务服务平台小程序的公积金服务公告

### 第3层：权威媒体（哨兵，用于兜底和交叉验证）
- 中新网、新华网、各地党报客户端的"公积金"关键词
- 微信公众号：各市公积金中心官方公众号大多有"政策发布"推送（可人工订阅作备份哨兵）

---

## 三、技术架构（推荐）

```
┌─────────────────────────────────────────────────────────┐
│ 调度层：cron / GitHub Actions / 云函数定时触发            │
│   ├─ 每日任务：监测"公告栏目"是否有新政策（轻量、只读）    │
│   └─ 每周任务：全量校验 + 字段级 diff + 生成变更报告      │
├─────────────────────────────────────────────────────────┤
│ 采集层：Python 脚本                                      │
│   ├─ watchers/   每城一个 watcher 配置（公告列表页URL+CSS选择器）│
│   ├─ fetcher.py  抓取列表页 → 提取标题/日期/链接          │
│   ├─ detector.py 关键词过滤（"缴存基数|贷款额度|提取|利率|首付|调整"）│
│   ├─ differ.py   与数据库字段比对，输出 change_log.json    │
│   └─ updater.py  人工确认后回写 gjj_policy_database.json   │
├─────────────────────────────────────────────────────────┤
│ 存储层：                                                 │
│   ├─ gjj_policy_database.json（主库，git 版本管理）      │
│   ├─ snapshots/YYYYMMDD.json（每次变更自动快照，可回滚）  │
│   └─ change_log.json（变更流水：何时、哪个城市、哪个字段、旧值→新值、来源）│
├─────────────────────────────────────────────────────────┤
│ 通知层：邮件 / 企业微信 / 飞书 webhook / Telegram Bot     │
└─────────────────────────────────────────────────────────┘
```

### 关键设计原则
1. **快照+diff，不做破坏性更新**：每次更新前自动快照，所有变更写入 change_log，可审计、可回滚。
2. **人机协同**：新政策命中后自动解析并生成"建议变更"，**人工确认后再写库**（政策数字错一个都是事故）；确认环节可做成一个简单的待审清单。
3. **两级频率**：
   - **每日**：只跑 134 个城市公告列表页（每个页面 1 个请求，约几分钟跑完），检测是否有新公告标题命中关键词。
   - **每周**：全量字段复核一次（抽样打开来源页验证链接有效性、修正失效URL）。
   - **每年6-7月加密**：缴存基数调整季，改为每日全量盯基数调整公告。
4. **URL 健康检查**：每周校验数据库中所有 source URL 的 HTTP 状态，失效链接标记待修复。

---

## 四、调度实现方式（按部署环境三选一）

### 方案A：本机/服务器 cron（最简单）
```cron
# 每天早上8点：公告监测（轻量）
0 8 * * *  cd /data/gjj && python watcher_daily.py >> logs/daily.log 2>&1
# 每周一早上9点：全量复核 + diff 报告
0 9 * * 1  cd /data/gjj && python weekly_audit.py >> logs/weekly.log 2>&1
# 6-7月加密为每日两次
0 8,18 * * * cd /data/gjj && python watcher_daily.py --season=base_adjust >> logs/season.log 2>&1
```

### 方案B：GitHub Actions（零成本、带版本管理，推荐个人/小团队）
- 仓库放数据库 JSON + 脚本，`schedule:` 触发器 `cron: '0 0 * * *'`
- 变更后自动 commit + 开 Pull Request 作为"人工确认"环节
- diff 直接体现在 PR 里，天然审计

### 方案C：本环境定时任务（最快起步）
本对话环境支持 cron 定时任务（add_cron_job）。如果你愿意，我可以直接帮你注册一个每周任务：每周自动巡检重点城市的公积金公告并输出变更摘要。需要的只是确认触发频率和关注城市范围。

---

## 五、核心脚本示例

### 5.1 每日公告监测 watcher_daily.py
```python
import json, hashlib, re, datetime, pathlib
import requests
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).parent
KEYWORDS = re.compile(r"缴存基数|贷款额度|最高额度|提取|利率|首付|调整|优化|新政")
SEEN_FILE = ROOT / "seen_announcements.json"   # 已见公告指纹库

def load_watchlist():
    # 从主库生成监测清单：每城的公告列表页 URL
    db = json.load(open(ROOT / "gjj_policy_database.json", encoding="utf-8"))
    return [(c["city"], c.get("notice_list_url")) for c in db["cities"] if c.get("notice_list_url")]

def fetch_titles(url):
    html = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"}).text
    soup = BeautifulSoup(html, "html.parser")
    # 选择器因站而异，watchlist 中可为每城配置 selector；此处为通用兜底
    return [(a.get_text(strip=True), a.get("href")) for a in soup.select("a")]

def main():
    seen = json.load(open(SEEN_FILE, encoding="utf-8")) if SEEN_FILE.exists() else {}
    hits = []
    for city, url in load_watchlist():
        try:
            for title, link in fetch_titles(url):
                fp = hashlib.md5(f"{city}{title}".encode()).hexdigest()
                if fp not in seen and KEYWORDS.search(title):
                    hits.append({"city": city, "title": title, "link": link,
                                 "date": datetime.date.today().isoformat()})
                    seen[fp] = datetime.date.today().isoformat()
        except Exception as e:
            print(f"[WARN] {city}: {e}")
    json.dump(seen, open(SEEN_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if hits:
        json.dump(hits, open(ROOT / f"hits_{datetime.date.today()}.json", "w",
                  encoding="utf-8"), ensure_ascii=False, indent=1)
        notify(hits)   # 发邮件/飞书 webhook

if __name__ == "__main__":
    main()
```

### 5.2 变更比对 differ.py（周复核用）
```python
import json, deepdiff   # pip install deepdiff

old = json.load(open("snapshots/latest.json", encoding="utf-8"))
new = json.load(open("gjj_policy_database.json", encoding="utf-8"))
diff = deepdiff.DeepDiff(old, new, ignore_order=True)
if diff:
    json.dump(diff.to_json(), open("change_log.json", "a", encoding="utf-8"))
    # 生成人类可读的变更摘要，供人工确认
```

### 5.3 半自动政策解析（进阶）
对新公告正文页，可用 LLM API 做结构化抽取（提示词中嵌入本数据库的 JSON Schema），输出"建议补丁 JSON"，人工点确认后 merge 进主库。这样 134 城的日常维护人力可压缩到每周 < 1 小时。

---

## 六、建议的落地路线图

| 阶段 | 周期 | 动作 |
|---|---|---|
| 第1周 | 一次性 | 为134城补齐 `notice_list_url`（公告列表页）和页面选择器配置 |
| 第2周 | 一次性 | 跑通每日监测脚本 + 通知渠道；接入 git 快照 |
| 持续 | 每日 | 自动巡检，命中新政策 → 推送待审清单 |
| 持续 | 每周一 | 全量复核 + URL 健康检查 + diff 报告 |
| 每年6-7月 | 加密 | 基数调整季每日两巡，重点盯 deposit 字段 |
```

---

## 七、风险与注意事项

1. **网站改版**：地方政府网站改版会导致选择器失效 → 监测脚本需有"连续N次抓取为空则报警"的兜底。
2. **反爬**：gov.cn 站点一般无强反爬，但需控制频率（每城每天1-2次请求足够），带正常 UA，尊重 robots.txt。
3. **政策生效日期 ≠ 发布日期**：入库时以"执行日期"为准，note 中记录发布日期。
4. **同一城市多中心**：少数城市存在省直/市直两个公积金中心（如杭州有省直分中心），数据归属需在 note 中注明。
5. **县级市/自治州**：如红河州、石河子（兵团）等特殊行政主体，政策发布主体可能是州/兵团中心，URL 归属需注意。
