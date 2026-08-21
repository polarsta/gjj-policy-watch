# SPEC.md — gjj-policy-watch 公积金政策监测系统

## 1. 项目目标
对 134 个中国城市住房公积金政策（缴存/提取/贷款）进行自动化监测与数据库更新。两条发现通道：
1. **Watcher 通道**：定向巡检各市公积金中心官网「通知公告」列表页。
2. **Searcher 通道（新增重点）**：按「城市名 + 公积金 + 政策关键词」进行搜索引擎检索，**限定日期范围**（默认最近7天，可配置），锁定最新政策信息，作为 watcher 的兜底与补充。

命中 → 关键词分类 → 与数据库 diff → 生成变更报告 → （可选 LLM 抽取补丁）→ 人工确认 → 快照+写库。

## 2. 仓库结构（最终交付，路径 /mnt/agents/output/project）
```
project/
├── README.md
├── requirements.txt          # requests, beautifulsoup4, pyyaml, lxml; 无其他重依赖
├── Dockerfile
├── .gitignore                # 忽略 data/seen_announcements.json, data/snapshots/, reports/, __pycache__, .env
├── .env.example              # 可选密钥：SERPAPI_KEY/TAVILY_KEY/BOCHA_KEY/OPENAI_*、SMTP_*、WEBHOOK_URL
├── gjjwatch/
│   ├── __init__.py           # __version__ = "1.0.0"
│   ├── config.py
│   ├── models.py
│   ├── fetcher.py
│   ├── watcher.py
│   ├── searcher.py
│   ├── detector.py
│   ├── differ.py
│   ├── updater.py
│   ├── notifier.py
│   ├── llm_extract.py
│   └── cli.py
├── config/
│   ├── settings.yaml
│   └── cities.yaml           # 134城，主代理已生成种子
├── scripts/
│   ├── crontab.example
│   └── run_daily.sh / run_weekly.sh
├── .github/workflows/
│   ├── daily.yml
│   └── weekly.yml
├── data/
│   ├── gjj_policy_database.json   # 主库（种子已存在，勿改结构）
│   └── README.md                  # 说明 seen/snapshots/change_log 等运行时文件
├── tests/
│   ├── test_detector.py
│   ├── test_differ.py
│   ├── test_searcher.py
│   ├── test_watcher.py
│   └── fixtures/             # 离线 HTML/JSON 样例，测试不得依赖外网
└── reports/                  # 运行时输出（gitignore）
```

## 3. 配置文件契约

### config/settings.yaml
```yaml
date_window_days: 7            # 搜索限定的日期范围（最近N天）
request_timeout: 15
request_delay: 1.0             # 每请求间隔秒数（礼貌限速）
user_agent: "Mozilla/5.0 (compatible; gjj-policy-watch/1.0)"
keywords:                      # detector 命中词
  - 缴存基数
  - 贷款额度
  - 最高额度
  - 提取
  - 利率
  - 首付
  - 调整
  - 优化
  - 新政
  - 通知
search:
  backend: bing_html           # bing_html | serpapi | tavily | bocha
  results_per_query: 10
  policy_terms: [贷款, 提取, 缴存, 利率, 首付]   # 与城市名组合成查询词
  domain_boost: ["gov.cn"]     # 结果排序加权
llm:
  enabled: false               # 需 OPENAI_API_KEY 才开启
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o-mini"
notify:
  console: true
  webhook_url: ""              # 企业微信/飞书 webhook，可空
  smtp: {enabled: false, host: "", port: 465, user: "", to: []}
paths:
  db: data/gjj_policy_database.json
  seen: data/seen_announcements.json
  snapshots: data/snapshots
  change_log: data/change_log.json
  reports: reports
```

### config/cities.yaml（主代理已生成，结构如下，不得更改 schema）
```yaml
- city: 深圳
  province: 广东
  official_site: "https://...或null"
  notice_list_url: null        # 待补充；为 null 时 watcher 跳过该城
  list_selector: "a"           # CSS选择器（列表页链接）
  search_aliases: ["深圳"]     # 搜索用别名（如"红河"→["红河州","红河"]）
```

## 4. 数据模型契约（gjjwatch/models.py，用 dataclass）
```python
@dataclass
class Announcement:
    city: str
    title: str
    url: str
    date: str | None           # ISO 或 None
    channel: str               # "watcher" | "search"
    snippet: str = ""
    fingerprint: str = ""      # md5(city+title+url)

@dataclass
class ChangeEvent:             # differ 输出
    city: str
    field_path: str            # 如 "loan.max_family"
    old_value: object
    new_value: object
    source_url: str
    detected_at: str           # ISO datetime

@dataclass
class ScanResult:              # 一次巡检的结果
    run_at: str
    announcements: list        # list[Announcement]，均为"新发现"（已去重）
    hits: list                 # 命中关键词的 Announcement
    errors: list[str]
```

## 5. 模块接口契约（函数签名必须完全一致）

### config.py
- `load_settings(path="config/settings.yaml") -> dict`
- `load_cities(path="config/cities.yaml") -> list[dict]`

### fetcher.py
- `fetch(url: str, settings: dict) -> str`：带 UA、超时、重试2次、限速 sleep(settings["request_delay"])；失败抛 `FetchError`
- `class FetchError(Exception)`

### watcher.py
- `scan_city(city_cfg: dict, settings: dict) -> list[Announcement]`：抓 notice_list_url，用 list_selector 提取 (title,url,date?)，channel="watcher"
- `scan_all(cities, settings, seen: dict) -> tuple[list[Announcement], dict]`：返回(新公告, 更新后的seen)；相对URL需转绝对；notice_list_url 为 null 的跳过

### searcher.py（本次重点模块）
- `build_queries(city_cfg: dict, settings: dict) -> list[str]`：对每个 alias × policy_terms 生成查询，如 "深圳 公积金 贷款"
- `search(query: str, settings: dict) -> list[dict]`：按 backend 分发；每项 {"title","url","snippet","date","engine"}
- `search_city(city_cfg, settings) -> list[Announcement]`：执行搜索→**日期过滤**（仅保留 date 在最近 settings["date_window_days"] 天内；无日期的保留但 snippet 标注）→ channel="search"
- `search_all(cities, settings, seen) -> tuple[list[Announcement], dict]`
- 后端实现：
  - `bing_html`：GET `https://www.bing.com/search?q=...&filters=ex1:"ez{N}"`（N=天数，Bing 内置日期范围参数），用 BeautifulSoup 解析 `li.b_algo`；无外部依赖、默认后端
  - `serpapi` / `tavily` / `bocha`：读对应 API KEY，调用其搜索 API，结果归一化为同一 dict 结构；KEY 缺失则跳过并记录 warning
- 所有后端失败须降级：有 KEY 的后端失败 → 回退 bing_html → 仍失败记录 error 不崩溃

### detector.py
- `is_hit(announcement: Announcement, settings) -> bool`
- `classify(announcement) -> list[str]`：返回命中类别子集 ["deposit","withdrawal","loan","rate","general"]（按关键词映射：缴存→deposit，提取→withdrawal，贷款/额度/首付→loan，利率→rate）
- `extract_date(text) -> str|None`：从标题/snippet 解析中文日期（2026年8月20日 / 2026-08-20 / 2026.8.20）

### differ.py
- `load_db(path) -> dict`
- `diff_db(old: dict, new: dict) -> list[ChangeEvent]`：仅比较 cities 数组内字段（按 city 对齐），忽略缩进/顺序
- `snapshot(db_path, snapshots_dir) -> str`：复制为 snapshots/YYYYMMDD_HHMMSS.json，返回路径

### updater.py
- `apply_patch(db: dict, patch: dict, source_url: str) -> dict`：patch 格式 {"city":..., "changes":{field_path: new_value}}；更新字段并追加 sources；last_updated 刷新；version 次版本+1
- `save_db(db, settings)`：先 snapshot 再原子写（tmp+rename），追加 change_log.json

### notifier.py
- `render_markdown(result: ScanResult, events: list[ChangeEvent]) -> str`
- `notify(result, events, settings)`：console 打印；webhook_url 非空则 POST {"msgtype":"markdown"...}（企业微信格式）；smtp.enabled 则发邮件；全部失败仅告警不崩溃

### llm_extract.py
- `extract_patch(announcement, settings) -> dict|None`：llm.enabled=false 或无 KEY → return None；否则抓正文→OpenAI 兼容 chat API，提示词要求输出 {"city","changes":{...},"confidence"} JSON；解析失败 return None

### cli.py（argparse，入口 `python -m gjjwatch.cli`）
- `daily`：watcher.scan_all + searcher.search_all → detector 过滤 → notifier.notify（不动数据库）
- `search --city 深圳 --days 30`：手动搜索单城（days 覆盖 settings）
- `weekly`：daily 全流程 + URL 健康检查（抽样校验 sources）+ 输出周报到 reports/weekly_YYYYMMDD.md
- `apply-patch --file patch.json`：updater 流程（人工确认后执行）
- `init-seen`：首次运行，把当前所有可见公告标记为已见（避免首日海量误报）

## 6. GitHub Actions
- daily.yml：每天 08:00 CST（cron `0 0 * * *`）跑 `python -m gjjwatch.cli daily`，把 reports 作为 artifact 上传；有 hits 时用 repository_dispatch/议题评论或 webhook 通知（用 secrets.WEBHOOK_URL）
- weekly.yml：每周一 09:00 CST 跑 weekly + `init-seen` 不适用；变更自动提交分支 + gh pr create（用 GITHUB_TOKEN），PR 即人工确认环节

## 7. Dockerfile
python:3.12-slim，安装 requirements，挂载 ./config ./data ./reports，ENTRYPOINT ["python","-m","gjjwatch.cli"]，CMD ["daily"]

## 8. 测试要求（pytest，全部离线）
- detector：关键词命中/分类/中文日期解析（含"2026年8月20日"→"2026-08-20"）
- searcher：用 fixtures 中的 bing HTML 样例测解析与日期过滤；build_queries 组合正确
- watcher：用 fixtures HTML 测列表提取与相对URL转绝对
- differ：构造 old/new db 测 ChangeEvent 输出；snapshot 文件生成

## 9. 分工（三个子代理，各自 git worktree + 分支）
- **分支 core**：config/models/fetcher/watcher/detector + 对应测试 + fixtures
- **分支 search**：searcher/notifier/llm_extract + 对应测试 + fixtures（bing 样例 HTML）
- **分支 ops**：cli/differ/updater + Dockerfile + workflows + scripts + README + data/README + 对应测试

三方都只依赖本 SPEC 的接口契约，互不 import 对方未列出的内部细节。README 用中文写，包含：快速开始（本地/GitHub Actions/Docker）、134城 notice_list_url 待补充说明、init-seen 首日初始化、人工确认工作流。
