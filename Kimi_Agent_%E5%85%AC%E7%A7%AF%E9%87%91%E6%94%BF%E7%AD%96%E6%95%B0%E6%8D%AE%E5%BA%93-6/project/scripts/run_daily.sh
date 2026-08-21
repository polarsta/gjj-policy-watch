#!/usr/bin/env bash
# 每日巡检脚本：双通道扫描 → 关键词过滤 → 通知（不修改数据库）
# 用法：scripts/run_daily.sh（cron 或手动均可）
set -euo pipefail

# 切到项目根目录（脚本位于 <root>/scripts/ 下）
cd "$(dirname "$0")/.."

# 加载本地密钥（如存在）
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

PYTHON="${PYTHON:-python3}"
exec "$PYTHON" -m gjjwatch.cli daily
