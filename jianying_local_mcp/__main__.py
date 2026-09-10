from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import ProjectStore, environment_status, inspect_draft, read_json


def main():
    parser = argparse.ArgumentParser(description="本地剪映 MCP 原型（草稿兼容性需应用内验证）")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="启动 stdio MCP 服务")
    sub.add_parser("doctor", help="检查本机剪映与支持能力")
    inspect = sub.add_parser("inspect", help="只读查看原生工程")
    inspect.add_argument("path")
    create = sub.add_parser("create", help="从 JSON 剪辑计划生成新的草稿包")
    create.add_argument("plan")
    create.add_argument("--workspace")
    create.add_argument("--write", action="store_true", help="实际生成；默认仅验证")
    publish = sub.add_parser("publish", help="将新草稿登记到剪映首页；实际执行前须完全退出剪映")
    publish.add_argument("name")
    publish.add_argument("--draft-root", required=True)
    publish.add_argument("--workspace")
    publish.add_argument("--write", action="store_true", help="实际发布；默认仅验证")
    args = parser.parse_args()
    if args.command in (None, "serve"):
        from .server import run
        run()
        return
    if args.command == "doctor":
        result = environment_status()
    elif args.command == "inspect":
        result = inspect_draft(args.path)
    elif args.command == "publish":
        from .publishing import publish_project
        result = publish_project(ProjectStore(args.workspace), args.name,
                                 args.draft_root, dry_run=not args.write)
    else:
        result = ProjectStore(args.workspace).create(read_json(Path(args.plan)), dry_run=not args.write)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
