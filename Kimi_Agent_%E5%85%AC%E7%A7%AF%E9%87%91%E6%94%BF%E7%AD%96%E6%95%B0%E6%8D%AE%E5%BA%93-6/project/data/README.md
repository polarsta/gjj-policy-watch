# data/ 运行时文件说明

本目录除主库外的文件均为**运行时生成**，已加入 `.gitignore`，请勿手工编辑。

| 文件/目录 | 生成时机 | 说明 |
| --- | --- | --- |
| `gjj_policy_database.json` | 种子文件（已入库） | 134 城公积金政策主库，结构勿改；只通过 `apply-patch` 更新 |
| `seen_announcements.json` | `daily` / `weekly` / `init-seen` | 已见公告指纹表（跨运行去重）。删除后会导致历史公告被当作新发现重复告警 |
| `snapshots/` | `apply-patch` 写库前 | 每次写库前的整库快照，文件名 `YYYYMMDD_HHMMSS.json`，用于回滚与审计 |
| `change_log.json` | `apply-patch` 写库后 | 变更日志（JSON 数组），每条含应用时间、版本号、对应快照与字段级 diff |

## 回滚方法

```bash
# 选择某个快照覆盖主库即可回滚
cp data/snapshots/20260820_080000.json data/gjj_policy_database.json
```

## 首日初始化

首次部署先执行 `python -m gjjwatch.cli init-seen`，把当前可见公告一次性标记为已见，
避免首日海量误报。此后 `daily` 只会报告新出现的公告。
