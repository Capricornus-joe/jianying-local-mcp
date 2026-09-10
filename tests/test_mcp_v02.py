"""v0.2 workflows exercised through a real MCP SDK stdio subprocess.

All media and cache fixtures are synthetic. Native files are inspected for
serialization invariants, not treated as evidence of native-app playback.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import wave

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import pytest

from jianying_local_mcp.media import ffmpeg_path


@pytest.fixture(scope="module")
def assets(tmp_path_factory):
    root = tmp_path_factory.mktemp("mcp-v02-synthetic-media")
    video = root / "合成画面.mp4"
    frame = root / "合成图片.png"
    sound = root / "静音.wav"
    subprocess.run([
        ffmpeg_path(), "-nostdin", "-v", "error", "-n", "-f", "lavfi",
        "-i", "testsrc2=size=160x120:rate=10:duration=6", "-f", "lavfi",
        "-i", "sine=frequency=440:sample_rate=48000:duration=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video),
    ], check=True, capture_output=True, timeout=45)
    subprocess.run([
        ffmpeg_path(), "-nostdin", "-v", "error", "-n", "-i", str(video),
        "-frames:v", "1", str(frame),
    ], check=True, capture_output=True, timeout=30)
    with wave.open(str(sound), "wb") as output:
        output.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        output.writeframes(b"\0\0" * 8000 * 6)
    return {"root": root, "video": video, "image": frame, "audio": sound}


def snapshot(root):
    """Include empty directories, names, and every file byte in no-write checks."""
    if not root.exists():
        return None
    return {str(path.relative_to(root)): (
        "directory" if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    ) for path in sorted(root.rglob("*"))}


def payload(response):
    assert not response.isError, response.content
    if response.structuredContent is not None:
        return response.structuredContent
    return json.loads(next(item.text for item in response.content if item.type == "text"))


async def call(session, tool_name, **arguments):
    # Legacy payload assertions explicitly request the optional full plan.
    if tool_name in ['add_srt', 'apply_motion_preset', 'apply_native_resource', 'batch_edit', 'create_draft', 'edit_draft', 'montage_create', 'reorder_track', 'ripple_delete', 'set_clip_features', 'style_subtitles'] :
        arguments["include_plan"] = True
    return payload(await session.call_tool(tool_name, arguments))


@asynccontextmanager
async def connected(workspace, cache_root=None):
    package_root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(package_root),
           "JIANYING_MCP_WORKSPACE": str(workspace)}
    args = ["-m", "jianying_local_mcp", "serve"]
    if cache_root is not None:
        # Change only the resource resolver's data root, before importing the
        # real server. Public tools, validation, builder and stdio stay intact.
        args = ["-c", "import functools,sys; import jianying_local_mcp.resources as r; "
                "r.resolve_resource=functools.partial(r.resolve_resource,cache_root=sys.argv[1]); "
                "from jianying_local_mcp.server import run; run()", str(cache_root)]
    params = StdioServerParameters(command=sys.executable, args=args, env=env, cwd=str(package_root))
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=45)) as session:
            assert (await session.initialize()).serverInfo.name == "Jianying Local MCP"
            yield session


def base_plan(assets, name="原始工程"):
    return {"name": name, "width": 320, "height": 180, "fps": 24, "clips": [
        {"id": "v1", "kind": "video", "track": "画面", "path": str(assets["video"]),
         "start": 0, "duration": 2, "source_start": .5, "speed": 2},
        {"id": "v2", "kind": "video", "track": "画面", "path": str(assets["video"]),
         "start": 2, "duration": 2, "source_start": 2},
        {"id": "t1", "kind": "text", "track": "字幕", "start": .25, "duration": 1.5,
         "text": "第一行😀\n<b>按字面保留</b>"},
        {"id": "t2", "kind": "text", "track": "字幕", "start": 2.5, "duration": 1,
         "text": "第二行🧑‍💻"},
        {"id": "a1", "kind": "audio", "track": "配乐", "path": str(assets["audio"]),
         "start": 0, "duration": 4},
    ]}


def by_id(result):
    return {clip["id"]: clip for clip in result["plan"]["clips"]}


def native(result):
    return json.loads((Path(result["project_dir"]) / "draft_info.json").read_text())


def native_track(document, name):
    return next(track["segments"] for track in document["tracks"] if track["name"] == name)


def test_workflows_protocol_wiring_and_all_dry_runs_leave_bytes_unchanged(assets, tmp_path):
    async def exercise():
        async with connected(tmp_path / "projects") as session:
            listed = {item.name for item in (await session.list_tools()).tools}
            assert {"reorder_track", "ripple_delete", "style_subtitles", "export_srt",
                    "montage_create", "set_clip_features", "apply_motion_preset",
                    "list_native_resources", "apply_native_resource", "process_media", "extract_frame"} <= listed
            presets = await call(session, "list_motion_presets")
            assert "pulse" in presets["presets"] and presets["easing"] == "linear"
            created = await call(session, "create_draft", plan=base_plan(assets), dry_run=False)
            assert created["status"] == "created"
            before, source_before = snapshot(tmp_path), snapshot(assets["root"])
            original = by_id(created)

            reordered = await call(session, "reorder_track", name="原始工程", new_name="排序预览",
                                   track="画面", clip_ids=["v2", "v1"], start=1.25)
            clips = by_id(reordered)
            assert clips["v2"]["start"] == 1.25 and clips["v1"]["start"] == 3.25
            assert all(clips[cid] == original[cid] for cid in ("t1", "t2", "a1"))

            rippled = await call(session, "ripple_delete", name="原始工程", new_name="删除预览", start=.75, end=1.25)
            video = sorted((c for c in rippled["plan"]["clips"] if c["track"] == "画面"), key=lambda c: c["start"])
            assert [(c["start"], c["duration"], c["source_start"]) for c in video] == [
                (0, .75, .5), (.75, .75, 3), (1.5, 2, 2)]
            assert by_id(rippled)["t2"]["start"] == 2
            audio = sorted((c for c in rippled["plan"]["clips"] if c["track"] == "配乐"), key=lambda c: c["start"])
            assert [(c["start"], c["duration"], c["source_start"]) for c in audio] == [(0, .75, 0), (.75, 2.75, 1.25)]

            styled = await call(session, "style_subtitles", name="原始工程", new_name="样式预览",
                                style={"font_size": 60, "color": "#abcdef", "x": .2, "y": -.5},
                                track="字幕", clip_ids=["t2"])
            assert by_id(styled)["t1"] == original["t1"]
            assert {k: by_id(styled)["t2"][k] for k in ("font_size", "color", "x", "y")} == {
                "font_size": 60, "color": "#ABCDEF", "x": .2, "y": -.5}
            srt = await call(session, "export_srt", name="原始工程", track="字幕")
            assert srt["cue_count"] == 2
            assert "00:00:00,250 --> 00:00:01,750\n第一行😀\n<b>按字面保留</b>" in srt["content"]
            assert "00:00:02,500 --> 00:00:03,500\n第二行🧑‍💻" in srt["content"]

            montage = await call(session, "montage_create", name="拼接预览",
                                 paths=[str(assets["video"]), str(assets["image"])],
                                 image_duration=.4, track="顺序素材", width=640, height=360, fps=25)
            assert (montage["summary"]["width"], montage["summary"]["height"], montage["summary"]["fps"]) == (640, 360, 25)
            assert [(c["kind"], c["start"], c["duration"], c["track"]) for c in montage["plan"]["clips"]] == [
                ("video", 0, 6, "顺序素材"), ("image", 6, .4, "顺序素材")]
            fixed = await call(session, "montage_create", name="定长预览", paths=[str(assets["video"])], clip_duration=1.25)
            assert fixed["plan"]["clips"][0]["duration"] == 1.25
            motion = await call(session, "apply_motion_preset", name="原始工程", new_name="运动预览",
                                clip_ids=["v1"], preset="pan_right", strength=.3)
            assert by_id(motion)["v1"]["keyframes"]["x"] == [{"time": 0, "value": -.3}, {"time": 2, "value": .3}]
            await call(session, "set_clip_features", name="原始工程", new_name="调整预览",
                       clip_ids=["v1"], features={"transform": {"rotation": 12}})
            processed = await call(session, "process_media", path=str(assets["video"]),
                                   output_dir=str(tmp_path / "未写入的素材"), operations={"brightness": .1})
            assert processed["output_kind"] == "video" and processed["operations"] == {"brightness": .1}
            extracted = await call(session, "extract_frame", path=str(assets["video"]), time=1.7,
                                   output_dir=str(tmp_path / "未写入的静帧"))
            assert extracted["source_time"] == 1.7 and extracted["output_kind"] == "image"

            for tool, arguments in [
                ("reorder_track", {"name": "原始工程", "new_name": "失败", "track": "画面", "clip_ids": ["v1"]}),
                ("ripple_delete", {"name": "原始工程", "new_name": "失败", "start": 2, "end": 1}),
                ("set_clip_features", {"name": "原始工程", "new_name": "失败", "clip_ids": ["missing"], "features": {"transform": {"x": 0}}}),
                ("set_clip_features", {"name": "原始工程", "new_name": "失败", "clip_ids": ["v1"], "features": {"transform": {"x": "NaN"}}}),
                ("process_media", {"path": str(assets["video"]), "output_dir": str(tmp_path / "bad"), "operations": {"gamma": "NaN"}}),
                ("extract_frame", {"path": str(assets["video"]), "time": 6, "output_dir": str(tmp_path / "bad")}),
                ("montage_create", {"name": "失败", "paths": [str(assets["audio"])]}),
            ]:
                assert (await session.call_tool(tool, {**arguments, "dry_run": False})).isError
            assert snapshot(tmp_path) == before
            assert snapshot(assets["root"]) == source_before

    asyncio.run(asyncio.wait_for(exercise(), timeout=90))


def test_feature_revisions_isolate_crops_and_keep_complete_unicode_style_runs(assets, tmp_path):
    async def exercise():
        async with connected(tmp_path / "projects") as session:
            created = await call(session, "create_draft", plan=base_plan(assets), dry_run=False)
            original = snapshot(Path(created["project_dir"]))
            cropped = await call(session, "set_clip_features", name="原始工程", new_name="只裁第一段",
                                 clip_ids=["v1"], features={"crop": {"left": .2, "right": .8, "top": .1, "bottom": .9}}, dry_run=False)
            styled = await call(session, "set_clip_features", name="只裁第一段", new_name="完整字幕",
                                clip_ids=["t1", "t2"], features={"text_style": {"bold": True, "stroke_color": "#102030", "stroke_width": 10}}, dry_run=False)
            document = native(styled)
            first, second = native_track(document, "画面")
            materials = {m["id"]: m for m in document["materials"]["videos"]}
            assert first["material_id"] != second["material_id"]
            assert materials[first["material_id"]]["path"] == materials[second["material_id"]]["path"]
            assert materials[first["material_id"]]["crop"]["upper_left_x"] == .2
            assert materials[second["material_id"]]["crop"]["upper_left_x"] == 0
            assert len(list((Path(styled["project_dir"]) / "Resources").glob("*.mp4"))) == 1
            for material in document["materials"]["texts"]:
                content = json.loads(material["content"])
                assert content["text"] in {"第一行😀\n<b>按字面保留</b>", "第二行🧑‍💻"}
                for style in content["styles"]:
                    assert style["range"] == [0, len(content["text"].encode("utf-16-le")) // 2]
                    assert style["bold"] is True and style["strokes"]
            cleared = await call(session, "set_clip_features", name="完整字幕", new_name="清除文字样式",
                                 clip_ids=["t2"], features={"text_style": None}, dry_run=False)
            assert "text_style" not in by_id(cleared)["t2"]
            assert by_id(cleared)["t1"]["text_style"]["bold"] is True
            assert by_id(cleared)["v1"]["crop"] == by_id(cropped)["v1"]["crop"]
            clear_document = native(cleared)
            for material in clear_document["materials"]["texts"]:
                content = json.loads(material["content"])
                if content["text"] == "第二行🧑‍💻":
                    assert content["styles"][0]["bold"] is False
                    assert content["styles"][0]["strokes"] == []
            assert snapshot(Path(created["project_dir"])) == original

    asyncio.run(asyncio.wait_for(exercise(), timeout=60))


def test_motion_split_keeps_speed_and_native_keyframe_boundary_then_clears_group(assets, tmp_path):
    async def exercise():
        async with connected(tmp_path / "projects") as session:
            await call(session, "create_draft", plan=base_plan(assets), dry_run=False)
            await call(session, "edit_draft", name="原始工程", new_name="片段起点偏移",
                       operations=[{"op": "update", "id": "v1", "changes": {"start": 4.5}}], dry_run=False)
            motion = await call(session, "apply_motion_preset", name="片段起点偏移", new_name="往返运动",
                                clip_ids=["v1"], preset="pulse", strength=.4, dry_run=False)
            before = snapshot(Path(motion["project_dir"]))
            split = await call(session, "edit_draft", name="往返运动", new_name="拆开并接续",
                               operations=[{"op": "split", "id": "v1", "at": 5.25}], dry_run=False)
            left = by_id(split)["v1"]
            right = next(c for c in split["plan"]["clips"] if c["track"] == "画面" and c["start"] == 5.25)
            assert (left["duration"], right["duration"], right["source_start"], right["speed"]) == (.75, 1.25, 2, 2)
            for prop in ("scale_x", "scale_y"):
                assert left["keyframes"][prop][-1]["value"] == pytest.approx(1.3)
                assert right["keyframes"][prop][0]["value"] == pytest.approx(1.3)
                assert right["keyframes"][prop][1] == {"time": .25, "value": 1.4}
                assert right["keyframes"][prop][-1] == {"time": 1.25, "value": 1}
            segments = native_track(native(split), "画面")
            left_native = next(s for s in segments if s["target_timerange"]["start"] == 4_500_000)
            right_native = next(s for s in segments if s["target_timerange"]["start"] == 5_250_000)
            assert right_native["source_timerange"] == {"start": 2_000_000, "duration": 2_500_000}
            for a, b in zip(left_native["common_keyframes"], right_native["common_keyframes"]):
                assert a["property_type"] == b["property_type"]
                assert a["keyframe_list"][-1]["values"] == b["keyframe_list"][0]["values"]
                assert a["keyframe_list"][-1]["time_offset"] == 750_000
                assert b["keyframe_list"][0]["time_offset"] == 0
            cleared = await call(session, "set_clip_features", name="拆开并接续", new_name="仅后半静止",
                                 clip_ids=[right["id"]], features={"keyframes": None}, dry_run=False)
            assert "keyframes" not in by_id(cleared)[right["id"]]
            assert by_id(cleared)["v1"]["keyframes"] == left["keyframes"]
            clear_native = next(s for s in native_track(native(cleared), "画面") if s["target_timerange"]["start"] == 5_250_000)
            assert clear_native["common_keyframes"] == []
            assert snapshot(Path(motion["project_dir"])) == before

    asyncio.run(asyncio.wait_for(exercise(), timeout=60))


def make_cache(cache):
    for resource_id in ("6798320778182922760", "6798320902548230669", "6724916044072227332"):
        directory = cache / resource_id / ("a" * 32)
        directory.mkdir(parents=True)
        (directory / "config.json").write_text(json.dumps({"effect": {"Link": [{"type": "InfoSticker"}]}}))
        (directory / "content.json").write_text(json.dumps({"filemap": {"prefab": "anim.prefab"}}))
        (directory / "anim.prefab").write_text("synthetic animation, never executed")
    directory = cache / "6724845717472416269" / ("b" * 32)
    (directory / "payload").mkdir(parents=True)
    (directory / "config.json").write_text(json.dumps({"effect": {"Link": [{"type": "AmazingFeature", "path": "payload/"}]}}))
    (directory / "payload/content.json").write_text("{}")
    (directory / "payload/main.scene").write_text("synthetic transition, never executed")


def test_reviewed_resource_cache_protocol_and_baked_media_roundtrip(assets, tmp_path):
    cache = tmp_path / "effect-cache"
    make_cache(cache)

    async def exercise():
        async with connected(tmp_path / "projects", cache) as session:
            await call(session, "create_draft", plan=base_plan(assets), dry_run=False)
            cache_before, all_before = snapshot(cache), snapshot(tmp_path)
            found = await call(session, "list_native_resources", kind="animation", query="渐显", cache_root=str(cache))
            assert found["count"] == found["cached_count"] == 2
            assert {r["kind"] for r in found["resources"]} == {"video_animation", "text_animation"}
            assert all(r["native_app_verified"] is False and r["entitlement_verified"] is False for r in found["resources"])
            transition = await call(session, "apply_native_resource", name="原始工程", new_name="转场预览", clip_ids=["v1"],
                                    resource_kind="transition", resource_name="叠化", duration=.3)
            assert by_id(transition)["v1"]["transition_out"]["duration"] == .3
            assert by_id(transition)["v1"]["transition_out"]["resource"]["resource_id"] == "6724845717472416269"
            text_animation = await call(session, "apply_native_resource", name="原始工程", new_name="字幕动画预览", clip_ids=["t1"],
                                        resource_kind="text_animation", resource_name="渐显", duration=.2)
            assert by_id(text_animation)["t1"]["animations"][0]["resource"]["resource_id"] == "6724916044072227332"
            for ids, kind, label in [(["t1"], "video_animation", "渐显"), (["v1"], "text_animation", "渐显"),
                                     (["v2"], "transition", "叠化"), (["v1"], "video_animation", "不存在")]:
                rejected = await session.call_tool("apply_native_resource", {"name": "原始工程", "new_name": "失败",
                    "clip_ids": ids, "resource_kind": kind, "resource_name": label, "dry_run": False})
                assert rejected.isError
            assert snapshot(tmp_path) == all_before

            await call(session, "apply_native_resource", name="原始工程", new_name="视频入场", clip_ids=["v1"],
                       resource_kind="video_animation", resource_name="渐显", duration=.25, dry_run=False)
            both = await call(session, "apply_native_resource", name="视频入场", new_name="视频出入场", clip_ids=["v1"],
                              resource_kind="video_animation", resource_name="渐隐", duration=.4, dry_run=False)
            assert {a["type"]: a["duration"] for a in by_id(both)["v1"]["animations"]} == {"in": .25, "out": .4}
            animations = native(both)["materials"]["material_animations"]
            assert len(animations) == 1
            assert {(a["type"], a["start"], a["duration"]) for a in animations[0]["animations"]} == {
                ("in", 0, 250_000), ("out", 1_600_000, 400_000)}
            rejected = await session.call_tool("edit_draft", {"name": "视频出入场", "new_name": "错误拆分",
                "operations": [{"op": "split", "id": "v1", "at": 1}], "dry_run": False})
            assert rejected.isError
            cleared = await call(session, "set_clip_features", name="视频出入场", new_name="清除原生动画", clip_ids=["v1"],
                                 features={"animations": None}, dry_run=False)
            assert "animations" not in by_id(cleared)["v1"]
            assert not native(cleared)["materials"].get("material_animations")

            processed = await call(session, "process_media", path=str(assets["video"]), output_dir=str(tmp_path / "预处理"),
                                   operations={"extract_audio": True, "normalize_audio": True}, dry_run=False)
            assert processed["output_kind"] == "audio" and Path(processed["output_path"]).is_file()
            audio_project = await call(session, "create_draft", plan={"name": "处理音频复用", "clips": [processed["reuse_clip"]]}, dry_run=False)
            assert audio_project["plan"]["clips"][0]["kind"] == "audio"
            frame = await call(session, "extract_frame", path=str(assets["video"]), time=1.2,
                               output_dir=str(tmp_path / "静帧"), dry_run=False)
            montage = await call(session, "montage_create", name="新静帧复用", paths=[frame["output_path"]], image_duration=.7, dry_run=False)
            assert montage["plan"]["clips"][0]["duration"] == .7
            assert snapshot(cache) == cache_before
            assert not (tmp_path / "projects/错误拆分").exists()

    asyncio.run(asyncio.wait_for(exercise(), timeout=120))
