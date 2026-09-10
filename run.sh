#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=${JIANYING_MCP_PYTHON:-"$PROJECT_DIR/.venv/bin/python"}
if [ ! -x "$PYTHON_BIN" ]; then
    printf '%s\n' '请先运行 bash setup.sh，或设置 JIANYING_MCP_PYTHON 指向已安装依赖的 Python。' >&2
    exit 1
fi
export PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}"
export JIANYING_MCP_WORKSPACE=${JIANYING_MCP_WORKSPACE:-"$PROJECT_DIR/projects"}
exec "$PYTHON_BIN" -m jianying_local_mcp "$@"
