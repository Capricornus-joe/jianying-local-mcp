"""Build a portable, self-contained 16-second v0.2 demonstration project.

Only generated media is used. Temporary source media is removed after the
managed project has copied it. This script never publishes or exports natively.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jianying_local_mcp.core import ProjectStore, project_name
from jianying_local_mcp.media import ffmpeg_path
from jianying_local_mcp.processing import extract_frame, process_media
from jianying_local_mcp.resources import resolve_resource


def synthesize(directory: Path) -> dict[str, Path]:
    """Generate two distinct moving patterns and a quiet 16-second chord."""
    files = {"video": directory / "moving-pattern.mp4",
             "inset": directory / "teal-pattern.mp4",
             "audio": directory / "synthetic-chord.wav"}
    ffmpeg = ffmpeg_path()
    video_source = "testsrc2=size=1280x720:rate=30:duration=4"
    recipes = [
        (["-f", "lavfi", "-i", video_source, "-c:v", "libx264", "-preset", "fast",
          "-crf", "20", "-pix_fmt", "yuv420p", "-threads", "2"], files["video"]),
        (["-f", "lavfi", "-i", video_source, "-vf", "hue=h=95:s=0.65",
          "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
          "-threads", "2"], files["inset"]),
        (["-f", "lavfi", "-i",
          "aevalsrc=0.03*sin(2*PI*220*t)+0.02*sin(2*PI*330*t)+0.015*sin(2*PI*440*t):s=48000:d=16",
          "-c:a", "pcm_s16le"], files["audio"]),
    ]
    for options, destination in recipes:
        try:
            completed = subprocess.run(
                [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
                 *options, str(destination)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Could not generate {destination.name}: {exc}") from exc
        if completed.returncode:
            raise ValueError(f"Could not generate {destination.name}: {completed.stderr.strip()[-1500:]}")
    return files


def cached_effects(enabled: bool, cache_root: str | None) -> dict:
    if not enabled:
        return {}
    fields = {"name", "effect_id", "resource_id", "path", "category_id", "category_name", "is_overlap"}
    effects = {}
    for key, kind, name in [("video_in", "video_animation", "渐显"),
                            ("text_in", "text_animation", "渐显"),
                            ("dissolve", "transition", "叠化")]:
        try:
            resolved = resolve_resource(kind, name, cache_root=cache_root)
        except (ValueError, OSError) as exc:
            raise ValueError(
                f"--with-cached-effects requires a unique downloaded {kind} resource '{name}': {exc}. "
                "Download it in Jianying, or omit --with-cached-effects. Nothing is downloaded automatically."
            ) from exc
        effects[key] = {k: v for k, v in resolved.items() if k in fields}
    return effects


def make_plan(name: str, files: dict[str, Path], reversed_path: str,
              frame_path: str, effects: dict) -> dict:
    clips = [
        {"id": "camera", "kind": "video", "track": "主画面", "path": str(files["video"]),
         "start": 0, "duration": 4, "keyframes": {
             "scale_x": [{"time": 0, "value": 1}, {"time": 4, "value": 1.35}],
             "scale_y": [{"time": 0, "value": 1}, {"time": 4, "value": 1.35}],
             "rotation": [{"time": 0, "value": -5}, {"time": 4, "value": 5}]}},
        {"id": "crop", "kind": "video", "track": "主画面", "path": reversed_path,
         "start": 4, "duration": 4,
         "crop": {"left": .15, "top": .1, "right": .85, "bottom": .9},
         "transform": {"flip_horizontal": True, "scale_x": .85, "scale_y": .85, "opacity": .85}},
        {"id": "circle", "kind": "video", "track": "主画面", "path": str(files["video"]),
         "start": 8, "duration": 4, "mask": {"shape": "circle", "height": .8, "feather": 0}},
        {"id": "freeze", "kind": "image", "track": "主画面", "path": frame_path,
         "start": 12, "duration": 4,
         "keyframes": {"opacity": [{"time": 0, "value": 0}, {"time": 4, "value": 1}]}},
        {"id": "pip", "kind": "video", "track": "画中画", "path": str(files["inset"]),
         "start": 4, "duration": 4,
         "transform": {"scale_x": .25, "scale_y": .25, "x": .65, "y": .6, "rotation": 10}},
        {"id": "rectangle", "kind": "video", "track": "圆角矩形", "path": str(files["inset"]),
         "start": 8, "duration": 4,
         "mask": {"shape": "rectangle", "width": .35, "height": .5, "round_corner": 20},
         "transform": {"x": -.6, "y": 0}},
    ]
    captions = ["关键帧推近 · 旋转 🎬", "裁剪镜像 · 画中画 · 调色倒放",
                "圆形与圆角矩形蒙版", "定格画面 · 透明度渐显 ✨"]
    for i, text in enumerate(captions):
        clips.append({"id": f"title{i}", "kind": "text", "track": "标题", "text": text,
                      "start": i * 4, "duration": 4, "font_size": 54, "y": -.78,
                      "color": "#FFDF64", "text_style": {
                          "bold": True, "stroke_color": "#000000", "stroke_width": 20,
                          "background_color": "#16202A", "background_opacity": .75,
                          "background_radius": .2, "shadow_color": "#000000",
                          "shadow_opacity": .6, "shadow_distance": 3}})
    clips.append({"id": "music", "kind": "audio", "track": "配乐", "path": str(files["audio"]),
                  "start": 0, "duration": 16, "volume": .7, "audio_fade": {"in": 1, "out": 1.5}})
    if effects:
        clips[0]["animations"] = [{"type": "in", "duration": .6, "resource": effects["video_in"]}]
        clips[2]["transition_out"] = {"duration": .6, "resource": effects["dissolve"]}
        clips[6]["animations"] = [{"type": "in", "duration": .6, "resource": effects["text_in"]}]
    return {"name": name, "width": 1280, "height": 720, "fps": 30, "clips": clips}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="MCP_V02_演示_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:6],
                        help="New project name; an existing project is never replaced")
    parser.add_argument("--workspace", type=Path, default=ROOT / "projects", help="Managed output workspace (default: package/projects)")
    parser.add_argument("--dry-run", action="store_true", help="Generate temporary media and validate; keep no project or generated assets")
    parser.add_argument("--with-cached-effects", action="store_true", help="Require downloaded video/text 渐显 and transition 叠化")
    parser.add_argument("--cache-root", help="Optional absolute Cache/effect directory, only used with --with-cached-effects")
    args = parser.parse_args()
    if args.cache_root and not args.with_cached_effects:
        parser.error("--cache-root requires --with-cached-effects")
    try:
        name = project_name(args.name)
        store = ProjectStore(args.workspace)
        target = store.workspace / name
        if target.exists() or target.is_symlink():
            raise ValueError("Project already exists; choose a different --name")
        effects = cached_effects(args.with_cached_effects, args.cache_root)
        print("正在生成临时合成素材并校验 16 秒工程……", file=sys.stderr, flush=True)
        with tempfile.TemporaryDirectory(prefix="jianying-v02-demo-") as temporary:
            directory = Path(temporary).resolve()
            files = synthesize(directory)
            processed = process_media(str(files["video"]), str(directory / "processed"),
                                      {"reverse": True, "saturation": .3, "contrast": 1.2}, dry_run=False)
            frame = extract_frame(str(files["video"]), 2, str(directory / "frames"), dry_run=False)
            plan = make_plan(name, files, processed["output_path"], frame["output_path"], effects)
            result = store.create(plan, dry_run=args.dry_run)
            if result["summary"]["duration"] != 16:
                raise RuntimeError("Demo duration verification failed")
            if not args.dry_run:
                info = json.loads((target / "draft_info.json").read_text(encoding="utf-8"))
                if info["duration"] != 16_000_000:
                    raise RuntimeError("Native timeline duration verification failed")
                managed = store.load_managed(name)
                for clip in managed["clips"]:
                    if "path" in clip:
                        media = Path(clip["path"])
                        if not media.is_relative_to(target / "Resources") or not media.is_file():
                            raise RuntimeError("Generated media was not bundled into the project")
        print(json.dumps({"status": result["status"], "dry_run": args.dry_run,
                          "project_dir": result["project_dir"], "summary": result["summary"],
                          "with_cached_effects": args.with_cached_effects,
                          "native_library_published": False,
                          "note": "试运行仅保留此摘要；临时素材已清理。" if args.dry_run else
                                  "合成素材已打包到工程 Resources；未发布到剪映原生库。"},
                         ensure_ascii=False, indent=2))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"创建示例失败：{exc}\n")


if __name__ == "__main__":
    main()
