#!/usr/bin/env bash
# 周报脚本：daily 全流程 + sources URL 抽样健康检查 → reports/weekly_YYYYMMDD.md
# 用法：scripts/run_weekly.sh（建议每周一 09:00 执行）
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
exec "$PYTHON" -m gjjwatch.cli weekly
