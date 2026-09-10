"""Exercise a real server subprocess through the official MCP stdio client."""

import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def tool_payload(response):
    assert not response.isError, response.content
    if response.structuredContent is not None:
        return response.structuredContent
    return json.loads(next(part.text for part in response.content if part.type == "text"))


def test_stdio_initialize_list_tools_and_readonly_dry_run(tmp_path):
    package_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "mcp-projects"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root)
    env["JIANYING_MCP_WORKSPACE"] = str(workspace)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "jianying_local_mcp", "serve"],
        env=env,
        cwd=str(package_root),
    )

    async def exercise():
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream, read_timeout_seconds=timedelta(seconds=15)) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "Jianying Local MCP"
                listed = await session.list_tools()
                tools = {tool.name: tool for tool in listed.tools}
                assert {"check_environment", "inspect_media", "read_native_draft", "list_managed_projects",
                        "read_managed_project", "create_draft", "edit_draft", "add_srt"} <= tools.keys()
                assert tools["check_environment"].annotations.readOnlyHint is True
                assert tools["create_draft"].annotations.destructiveHint is False
                environment = tool_payload(await session.call_tool("check_environment", {}))
                assert environment["transport"] == "stdio"
                assert environment["network_uploads"] is False
                assert environment["native_app_verified"] is False
                draft = tool_payload(await session.call_tool("create_draft", {
                    "plan": {"name": "MCP协议测试", "clips": [{"kind": "text", "text": "协议调用测试",
                             "track": "字幕", "start": 0, "duration": 2}]},
                    "dry_run": True, "include_plan": True,
                }))
                assert draft["status"] == "validated"
                assert draft["dry_run"] is True
                assert draft["summary"]["clip_count"] == 1
                assert draft["plan"]["clips"][0]["text"] == "协议调用测试"
                assert Path(draft["project_dir"]) == workspace / "MCP协议测试"
                listing = tool_payload(await session.call_tool("list_managed_projects", {}))
                assert listing["projects"] == []
                rejected = await session.call_tool("create_draft", {"plan": {"name": "../escape"}, "dry_run": False})
                assert rejected.isError is True
                assert not workspace.exists()

    asyncio.run(asyncio.wait_for(exercise(), timeout=30))
    assert not workspace.exists()
    assert not (tmp_path / "escape").exists()
