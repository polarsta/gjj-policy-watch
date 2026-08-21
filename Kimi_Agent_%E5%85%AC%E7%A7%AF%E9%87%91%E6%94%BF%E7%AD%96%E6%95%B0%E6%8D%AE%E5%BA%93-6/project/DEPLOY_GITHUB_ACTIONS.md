# GitHub Actions 部署指南 — gjj-policy-watch

仓库已内置两个工作流，推送后即可自动运行，无需改代码。

## 一、3 分钟部署

```bash
# 1. 解压仓库包
unzip gjj-policy-watch.zip && cd project

# 2. 在 GitHub 网页新建一个【私有仓库】，如 gjj-policy-watch（不要勾选初始化README）

# 3. 推送（本地分支已是 main，与 GitHub 默认分支一致）
git remote add origin git@github.com:<你的用户名>/gjj-policy-watch.git
git push -u origin main
```

推送完成后，Actions 自动就绪：
- **daily**：每天 08:00（北京时间）巡检 134 城，输出存为 Actions Artifacts
- **weekly**：每周一 09:00 全量复核 + URL 健康检查，有变更时**自动创建 Pull Request**（PR 即人工确认环节，审阅无误后点 Merge 完成数据库更新）

## 二、配置 Secrets（可选，按需）

仓库 → Settings → Secrets and variables → Actions → New repository secret：

| Secret | 作用 | 不配会怎样 |
|---|---|---|
| `WEBHOOK_URL` | 企业微信/飞书群机器人地址，命中新政策或任务失败时推送提醒 | 只在 Actions 页面查看结果 |
| `SERPAPI_KEY` | 搜索后端（任选其一即可增强稳定性） | 自动使用免费的 bing_html 后端 |
| `TAVILY_KEY` | 同上 | 同上 |
| `BOCHA_KEY` | 同上（国内服务，对中文政务内容覆盖较好） | 同上 |

不配任何 Secret 也能跑通完整流程。

## 三、首次运行（重要）

到 Actions 页面 → 选 "daily" 工作流 → **Run workflow** 手动触发前，建议先本地执行一次：

```bash
python -m gjjwatch.cli init-seen   # 把存量信息标记为已见，避免首日海量误报
```

或不执行也可以——首日报告会较长，之后即正常增量推送。

## 四、日常使用节奏

| 动作 | 频率 | 你要做的 |
|---|---|---|
| daily 巡检 | 每天 08:00 | 无需操作；有 webhook 时命中即收推送 |
| weekly 周报+PR | 每周一 09:00 | 收到 PR 后审阅 diff → Merge 即完成数据更新 |
| 单城手动核查 | 随时 | Actions 页手动触发，或本地 `python -m gjjwatch.cli search --city 杭州 --days 30` |
| 基数调整季 | 每年 6-7 月 | 把 daily.yml 的 cron 改为 `"0 0,10 * * *"`（每日两次），或保持每日+勤看周报 |

## 五、注意事项

1. **定时任务跑在默认分支（main）上**，工作流文件的修改须合入 main 才生效。
2. GitHub 免费版 Actions 对私有仓库每月 2000 分钟，本项目每次运行约 10–30 分钟，月消耗约 600–1000 分钟，额度够用；公开仓库则完全免费。
3. GitHub 定时任务可能有数分钟延迟，且仓库 60 天无活动会被暂停定时任务（每周有 PR/commit 即不会触发）。
4. 巡检 134 城的默认后端是 Bing 网页搜索，若某时段结果变差，在 `config/settings.yaml` 把 `search.backend` 改为已配 KEY 的后端即可无缝切换。
5. `data/seen_announcements.json` 通过 Actions Cache 跨运行保留，保证增量去重。
