# gjj-policy-watch 公积金政策监测系统

对全国 134 个城市住房公积金政策（缴存 / 提取 / 贷款）进行自动化监测与数据库维护。
发现政策变动 → 关键词分类 → 与数据库 diff → 生成变更报告 →（可选 LLM 抽取补丁）→
**人工确认** → 快照 + 写库。

## 两条发现通道

1. **Watcher 通道（官网公告巡检）**：定向抓取各市公积金中心官网「通知公告」列表页
   （`config/cities.yaml` 中的 `notice_list_url`），按 CSS 选择器提取标题/链接/日期。
2. **Searcher 通道（搜索引擎兜底）**：按「城市别名 × 政策关键词」组合查询词
   （如 `深圳 公积金 贷款`）调用搜索引擎，**限定日期范围**（默认最近 7 天，
   `config/settings.yaml` 的 `date_window_days`），锁定最新政策信息。
   默认使用无需密钥的 `bing_html` 后端；配置 `SERPAPI_KEY` / `TAVILY_KEY` / `BOCHA_KEY`
   后可切换对应 API 后端，失败自动降级回 `bing_html`。

命中结果按关键词分类（缴存 deposit / 提取 withdrawal / 贷款 loan / 利率 rate），
跨运行通过 `data/seen_announcements.json` 指纹去重，只报告新发现。

## 快速开始

### 本地运行

```bash
pip install -r requirements.txt   # 测试还需 pip install pytest

# 首次部署：首日初始化，把当前可见公告标记为已见，避免海量误报
python -m gjjwatch.cli init-seen

# 每日巡检（不动数据库）
python -m gjjwatch.cli daily

# 手动搜索单城（--days 覆盖默认日期窗口）
python -m gjjwatch.cli search --city 深圳 --days 30

# 周报（含来源链接抽样健康检查，输出 reports/weekly_YYYYMMDD.md）
python -m gjjwatch.cli weekly

# 人工确认后应用补丁（快照 + 原子写库 + 变更日志）
python -m gjjwatch.cli apply-patch --file patch.json

# 离线测试
pytest
```

### GitHub Actions

- `daily.yml`：每天 08:00（CST）自动巡检，巡检输出作为 artifact 上传；
  配置 `Settings → Secrets → WEBHOOK_URL`（企业微信/飞书 webhook）后接收命中与失败通知。
- `weekly.yml`：每周一 09:00（CST）跑周报；有变更时**自动建分支并创建 PR，
  PR 即人工确认环节**，审阅无误后合并。
- 建议同时配置 `SERPAPI_KEY` / `TAVILY_KEY` / `BOCHA_KEY` secrets 以启用更稳定的搜索后端。

### Docker

```bash
docker build -t gjj-policy-watch .
# 挂载 config / data / reports 持久化；默认执行 daily
docker run --rm \
  -v "$PWD/config:/app/config" \
  -v "$PWD/data:/app/data" \
  -v "$PWD/reports:/app/reports" \
  gjj-policy-watch            # 等价于 daily
# 其他子命令直接跟在镜像名后，例如：
docker run --rm -v "$PWD/config:/app/config" -v "$PWD/data:/app/data" gjj-policy-watch weekly
```

### 服务器 cron

参考 `scripts/crontab.example`：每日 08:00 跑 `scripts/run_daily.sh`，每周一 09:00 跑
`scripts/run_weekly.sh`；**6-7 月基数调整季**可按文件内注释示例加密为每日两次。

## 维护指南：134 城 notice_list_url 待补充

`config/cities.yaml` 已含 134 城种子，但多数城市的 `notice_list_url` 仍为 `null`——
**为 null 时 watcher 自动跳过该城**，仅由 searcher 搜索通道兜底。补录方法：

1. 打开该市公积金中心官网（`official_site` 已给出），找到「通知公告/新闻动态」列表页 URL；
2. 填入 `notice_list_url`；
3. 如列表页结构特殊，调整 `list_selector`（提取链接的 CSS 选择器，默认 `a`）；
4. 个别城市搜索词有歧义时（如"红河"），在 `search_aliases` 增加别名（如 `红河州`）。

欢迎直接提 PR 补录各城列表页。

## 人工确认工作流

系统**不会自动改写政策数据库**。标准流程：

1. `daily` / `weekly` 发现政策变动并通知（console / webhook / SMTP）；
2. 维护者阅读报告，人工核对原文（可选：开启 `llm.enabled` 自动生成补丁草稿）；
3. 按格式编写补丁文件 `patch.json`：
   ```json
   {
     "city": "深圳",
     "source_url": "https://zjj.sz.gov.cn/.../通知原文.html",
     "changes": {
       "loan.max_family": "240万元",
       "deposit.base_upper": 46000
     }
   }
   ```
4. 执行 `python -m gjjwatch.cli apply-patch --file patch.json`：
   写库前先整库快照到 `data/snapshots/YYYYMMDD_HHMMSS.json`，原子写库，
   `version` 次版本号 +1，该城 `last_updated` 刷新，来源 URL 追加到对应小节 `sources`，
   并在 `data/change_log.json` 追加一条字段级变更记录；
5. GitHub Actions 场景下，`weekly.yml` 会把变更开成 PR，合并即最终确认。

回滚：用 `data/snapshots/` 中任一快照覆盖 `data/gjj_policy_database.json` 即可。

## 目录结构

```
├── gjjwatch/            # 主程序包
│   ├── config.py        # 配置加载
│   ├── models.py        # Announcement / ChangeEvent / ScanResult
│   ├── fetcher.py       # 带限速/重试的抓取
│   ├── watcher.py       # 通道一：官网公告巡检
│   ├── searcher.py      # 通道二：限定日期范围的搜索引擎检索
│   ├── detector.py      # 关键词命中与分类
│   ├── differ.py        # 数据库 diff 与快照
│   ├── updater.py       # 补丁应用与原子写库
│   ├── notifier.py      # console / webhook / SMTP 通知
│   ├── llm_extract.py   # 可选 LLM 补丁草稿抽取
│   └── cli.py           # 命令行入口（daily/search/weekly/apply-patch/init-seen）
├── config/
│   ├── settings.yaml    # 全局设置（关键词/搜索后端/通知/路径）
│   └── cities.yaml      # 134 城配置（notice_list_url 待持续补录）
├── data/
│   ├── gjj_policy_database.json  # 政策主库
│   └── README.md        # seen/snapshots/change_log 运行时文件说明
├── scripts/             # crontab 示例与 daily/weekly 包装脚本
├── .github/workflows/   # daily.yml / weekly.yml
├── tests/               # pytest 离线测试（含 fixtures）
└── reports/             # 运行时报告输出（gitignore）
```

## 环境变量

见 `.env.example`：搜索后端 Key（SERPAPI/TAVILY/BOCHA）、LLM（OPENAI_API_KEY/BASE_URL）、
SMTP、WEBHOOK_URL 均可选，缺失时对应功能自动跳过或降级。
