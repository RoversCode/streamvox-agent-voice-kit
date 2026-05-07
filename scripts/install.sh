#!/usr/bin/env bash
set -euo pipefail

# 关键变量：ROOT 固定指向仓库根目录，保证脚本从任意目录触发时都能定位本地 bootstrap 模块。
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

cd "$ROOT"
exec "$PYTHON_BIN" -m streamvox_agent_voice.bootstrap "$@"
