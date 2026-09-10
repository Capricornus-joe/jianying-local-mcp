#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=${JIANYING_SETUP_PYTHON:-python3}
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,11), "需要 Python 3.11 或更新版本"'
if [ ! -x "$PROJECT_DIR/.venv/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$PROJECT_DIR/.venv"
fi
"$PROJECT_DIR/.venv/bin/python" -m pip install -e "$PROJECT_DIR[test]"
printf '%s\n' '安装完成。运行 ./run.sh doctor 检查环境；./run.sh 启动 MCP。'
