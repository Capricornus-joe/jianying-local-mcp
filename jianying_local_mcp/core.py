"""Validation and immutable project revisions; never edit a user's source draft."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import shutil
import tempfile
from uuid import uuid4

from . import __version__
from .media import probe_media
from .advanced import ADVANCED_FIELDS, normalize_advanced, sliced_keyframes
from .native import validate_display_name

MANIFEST = "jianying_mcp_project.json"
MAX_JSON = 64 * 1024 * 1024
# Half a centisecond plus one microsecond matches native validation and the
# precision of FFmpeg's human-readable duration for non-PCM-WAV inputs.
SOURCE_RANGE_TOLERANCE = 0.005001
TOP_FIELDS = {"name", "id", "width", "height", "fps", "clips"}
CLIP_FIELDS = {"id", "kind", "track", "start", "duration", "source_start", "speed", "volume",
               "path", "media_duration", "media_width", "media_height", "has_audio", "text",
               "font_size", "color", "x", "y", "display_name"}
EDIT_FIELDS = {"start", "duration", "source_start", "speed", "volume", "text", "font_size", "color", "x", "y", "track", "display_name"}
CLIP_FIELDS |= ADVANCED_FIELDS
EDIT_FIELDS |= ADVANCED_FIELDS


def number(value, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        n = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(n) or not low <= n <= high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return n


def label(value, field: str, maximum=100) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters")
    if any(ord(c) < 32 for c in value):
        raise ValueError(f"{field} contains control characters")
    return value


def project_name(value) -> str:
    value = label(value, "name", 80)
    if value != value.strip() or value.startswith(".") or any(c in value for c in '/\\:'):
        raise ValueError("Project name must be a single visible folder name without slashes or colon")
    return value


def read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_JSON:
        raise ValueError("Draft is larger than the 64 MB inspection limit")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("NON_PLAINTEXT_DRAFT: this file is not readable JSON; no decryption is attempted") from exc
    if not isinstance(data, dict):
        raise ValueError("A draft must contain a JSON object")
    return data


def normalize_plan(plan: dict, probe=probe_media) -> dict:
    if not isinstance(plan, dict) or set(plan) - TOP_FIELDS:
        raise ValueError(f"Allowed plan fields: {', '.join(sorted(TOP_FIELDS))}")
    name = project_name(plan.get("name"))
    width = number(plan.get("width", 1920), "width", 64, 7680)
    height = number(plan.get("height", 1080), "height", 64, 7680)
    if int(width) != width or int(height) != height:
        raise ValueError("Canvas dimensions must be integers")
    fps = number(plan.get("fps", 30), "fps", 1, 120)
    raw_clips = plan.get("clips", [])
    if not isinstance(raw_clips, list) or len(raw_clips) > 2000:
        raise ValueError("clips must be a list containing at most 2000 segments")
    out = {"id": str(uuid4()), "name": name, "width": int(width), "height": int(height), "fps": fps, "clips": []}
    ids, track_types, ranges, media_cache = set(), {}, {}, {}
    for i, raw in enumerate(raw_clips):
        if not isinstance(raw, dict) or set(raw) - CLIP_FIELDS:
            raise ValueError(f"Clip {i}: unknown fields or not an object")
        kind = raw.get("kind")
        if kind not in {"video", "audio", "image", "text"}:
            raise ValueError(f"Clip {i}: kind must be video, audio, image or text")
        cid = raw.get("id", str(uuid4()))
        if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", cid) or cid in ids:
            raise ValueError(f"Clip {i}: id must be unique ASCII letters, digits, hyphens or underscores")
        ids.add(cid)
        track = label(raw.get("track", kind), "track", 80)
        track_type = "video" if kind == "image" else kind
        if track in track_types and track_types[track] != track_type:
            raise ValueError(f"Track {track}: cannot mix video, audio and text")
        track_types[track] = track_type
        start = number(raw.get("start", 0), f"Clip {cid} start", 0, 86400)
        duration = number(raw.get("duration"), f"Clip {cid} duration", 0.001, 86400)
        if start + duration > 86400:
            raise ValueError("Timeline exceeds the 24 hour limit")
        speed = number(raw.get("speed", 1), f"Clip {cid} speed", 0.1, 16)
        source_start = number(raw.get("source_start", 0), "source_start", 0, 86400)
        if kind in {"text", "image"} and (speed != 1 or source_start != 0):
            raise ValueError("Text and images require speed=1 and source_start=0")
        clip = {"id": cid, "kind": kind, "track": track, "start": start, "duration": duration,
                "speed": speed, "source_start": source_start,
                "volume": number(raw.get("volume", 1), "volume", 0, 4),
                "x": number(raw.get("x", 0), "x", -1, 1),
                "y": number(raw.get("y", -0.75 if kind == "text" else 0), "y", -1, 1)}
        if "display_name" in raw:
            if kind == "text":
                raise ValueError("display_name is only supported for video, image and audio clips")
            clip["display_name"] = validate_display_name(raw["display_name"])
        if kind == "text":
            text = raw.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 20000:
                raise ValueError("Text clips require 1–20000 characters")
            if any((ord(c) < 32 and c not in "\n\t") or 0xD800 <= ord(c) <= 0xDFFF for c in text):
                raise ValueError("Subtitle contains invalid control characters")
            color = raw.get("color", "#FFFFFF")
            if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                raise ValueError("Text color must be #RRGGBB")
            clip.update(text=text, color=color.upper(), font_size=number(raw.get("font_size", 48), "font_size", 6, 576))
        else:
            media_path = raw.get("path")
            if not isinstance(media_path, str):
                raise ValueError(f"Clip {cid} requires a local media path")
            if media_path not in media_cache:
                media_cache[media_path] = probe(media_path)
            media = media_cache[media_path]
            if kind != media["kind"]:
                raise ValueError(f"Clip {cid}: requested {kind}, actual media is {media['kind']}")
            if abs(media.get("rotation", 0)) > 0.01:
                raise ValueError("Rotated media metadata is not yet supported; normalize orientation first")
            md = media["duration"]
            if kind != "image" and (md is None or source_start + duration * speed > md + SOURCE_RANGE_TOLERANCE):
                raise ValueError(f"Clip {cid}: source range exceeds media duration or duration is unknown")
            clip.update(path=media["path"], media_duration=md or duration,
                        media_width=media["width"], media_height=media["height"], has_audio=media["has_audio"])
        clip.update(normalize_advanced(raw, kind, duration))
        ranges.setdefault(track, []).append((start, start + duration, cid))
        out["clips"].append(clip)
    for track, entries in ranges.items():
        previous_end = -1.0
        for start, end, cid in sorted(entries):
            if start < previous_end - 0.000001:
                raise ValueError(f"Track {track}: overlapping clip {cid}; use a separate track for overlays")
            previous_end = end
    for track in track_types:
        clips=sorted((c for c in out['clips'] if c['track']==track),key=lambda c:c['start'])
        for index,clip in enumerate(clips):
            if not clip.get('transition_out'): continue
            if index+1==len(clips): raise ValueError('A transition must have a following clip on the same track')
            following=clips[index+1]
            if abs(clip['start']+clip['duration']-following['start'])>1e-6:
                raise ValueError('Transitions require adjacent clips with no gap')
            transition_duration=clip['transition_out']['duration']
            if transition_duration>min(clip['duration'],following['duration']):
                raise ValueError('Transition cannot exceed either neighboring clip duration')
    return out


def summarize(plan: dict) -> dict:
    return {"name": plan["name"], "width": plan["width"], "height": plan["height"], "fps": plan["fps"],
            "duration": round(max((c["start"] + c["duration"] for c in plan["clips"]), default=0), 6),
            "clip_count": len(plan["clips"]), "tracks": list(dict.fromkeys(c["track"] for c in plan["clips"]))}


class ProjectStore:
    def __init__(self, workspace: str | Path | None = None, probe=probe_media):
        default = Path(__file__).resolve().parent.parent / "projects"
        self.workspace = Path(workspace or os.environ.get("JIANYING_MCP_WORKSPACE", default)).expanduser().resolve()
        self.probe = probe

    def create(self, plan: dict, dry_run: bool = True) -> dict:
        normalized = normalize_plan(plan, self.probe)
        target = self.workspace / normalized["name"]
        if target.exists() or target.is_symlink():
            raise ValueError("A project with that name already exists; use a new revision name")
        from .native import build_native
        # The builder is pure: schema validation also belongs in previews so
        # dry runs cannot approve a plan that the native serializer rejects.
        build_native(normalized, target)
        summary = summarize(normalized)
        base = {"status": "validated" if dry_run else "created", "dry_run": dry_run, "summary": summary,
                "project_dir": str(target), "native_app_verified": False,
                "compatibility": "experimental_mac_draft; opening and export require Jianying verification"}
        if dry_run:
            base["plan"] = normalized
            return base
        self.workspace.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=self.workspace))
        try:
            (staging / "Resources").mkdir()
            copied, media_total = {}, 0
            for clip in normalized["clips"]:
                if "path" not in clip:
                    continue
                source = Path(clip["path"])
                if source not in copied:
                    media_total += source.stat().st_size
                    if media_total > 10 * 1024**3:
                        raise ValueError("Self-contained prototype project is limited to 10 GB of media")
                    dest_name = f"{len(copied)+1:04d}{source.suffix.lower()}"
                    shutil.copyfile(source, staging / "Resources" / dest_name)
                    copied[source] = str(target / "Resources" / dest_name)
                clip["path"] = copied[source]
            files = build_native(normalized, target)
            now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
            files["draft_meta_info.json"].update(tm_draft_create=now_us, tm_draft_modified=now_us,
                                                 draft_timeline_materials_size_=media_total)
            for filename in ("draft_info.json", "draft_meta_info.json"):
                if filename not in files or not isinstance(files[filename], dict):
                    raise ValueError("Native builder did not produce required Mac draft documents")
                (staging / filename).write_text(json.dumps(files[filename], ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            manifest = {"format": "jianying-local-mcp", "format_version": 1, "tool_version": __version__,
                        "created_at": datetime.now(timezone.utc).isoformat(), "native_app_verified": False, "plan": normalized}
            (staging / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            # A reserved destination directory prevents concurrent creation from overwriting a project.
            target.mkdir(exist_ok=False)
            try:
                for item in staging.iterdir():
                    shutil.move(str(item), str(target / item.name))
            except BaseException:
                shutil.rmtree(target)
                raise
            base["plan"] = normalized
            return base
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def load_managed(self, name: str) -> dict:
        name = project_name(name)
        target = self.workspace / name
        if target.is_symlink() or target.resolve().parent != self.workspace:
            raise ValueError("Project must be a direct, non-symlink child of the workspace")
        manifest = read_json(target / MANIFEST)
        if manifest.get("format") != "jianying-local-mcp" or manifest.get("format_version") != 1:
            raise ValueError("Only this MCP's managed projects can be revised")
        plan = manifest.get("plan")
        if not isinstance(plan, dict) or not isinstance(plan.get("clips"), list):
            raise ValueError("Managed project manifest must contain a plan object with a clips list")
        if any(not isinstance(clip, dict) for clip in plan["clips"]):
            raise ValueError("Managed project manifest clips must be objects")
        try:
            project_name(plan.get("name"))
            number(plan.get("width"), "width", 64, 7680)
            number(plan.get("height"), "height", 64, 7680)
            number(plan.get("fps"), "fps", 1, 120)
            for clip in plan["clips"]:
                label(clip.get("id"), "clip id", 80)
                label(clip.get("track"), "track", 80)
                number(clip.get("start"), "start", 0, 86400)
                number(clip.get("duration"), "duration", 0.001, 86400)
                if "display_name" in clip:
                    validate_display_name(clip["display_name"])
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"Invalid managed project manifest: {exc}") from exc
        return plan

    def edit(self, name: str, new_name: str, operations: list[dict], dry_run: bool = True) -> dict:
        plan = deepcopy(self.load_managed(name))
        plan["name"] = project_name(new_name)
        if not isinstance(operations, list) or not 1 <= len(operations) <= 2000:
            raise ValueError("Provide 1–2000 edit operations")
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError("Each operation must be an object")
            op = operation.get("op")
            allowed = {"append": {"op", "clip"}, "remove": {"op", "id"}, "update": {"op", "id", "changes"}, "split": {"op", "id", "at"}}
            if op not in allowed or set(operation) != allowed[op]:
                raise ValueError("Supported operations: append(clip), remove(id), update(id, changes), split(id, at)")
            if op == "append":
                plan["clips"].append(deepcopy(operation["clip"]))
                continue
            clip = next((c for c in plan["clips"] if c["id"] == operation["id"]), None)
            if clip is None:
                raise ValueError(f"Unknown clip id: {operation['id']}")
            if op == "remove":
                plan["clips"].remove(clip)
            elif op == "update":
                changes = operation["changes"]
                if not isinstance(changes, dict) or not changes or set(changes) - EDIT_FIELDS:
                    raise ValueError(f"Allowed update fields: {', '.join(sorted(EDIT_FIELDS))}")
                clip.update(changes)
            else:
                at = number(operation["at"], "split at", 0, 86400)
                relative = at - clip["start"]
                if not 0.001 <= relative <= clip["duration"] - 0.001:
                    raise ValueError("Split time must be strictly inside the clip (timeline seconds)")
                if any(clip.get('audio_fade',{}).values()) or clip.get('animations') or clip.get('transition_out'):
                    raise ValueError('Split clips before applying fades, native animations or transitions to preserve their timing')
                after = deepcopy(clip)
                if clip.get('keyframes'):
                    after['keyframes'] = sliced_keyframes(clip['keyframes'], relative, clip['duration'])
                    clip['keyframes'] = sliced_keyframes(clip['keyframes'], 0, relative)
                after["id"] = str(uuid4())
                after["start"] = at
                after["duration"] -= relative
                if clip["kind"] in {"video", "audio"}:
                    after["source_start"] += relative * clip["speed"]
                clip["duration"] = relative
                plan["clips"].insert(plan["clips"].index(clip) + 1, after)
        result = self.create(plan, dry_run=dry_run)
        result["source_project_unchanged"] = name
        return result

    def list_projects(self) -> list[dict]:
        if not self.workspace.exists():
            return []
        results = []
        for p in sorted(self.workspace.iterdir()):
            if p.is_dir() and not p.is_symlink() and (p / MANIFEST).is_file():
                try:
                    results.append(summarize(self.load_managed(p.name)))
                except (ValueError, OSError, KeyError, TypeError, AttributeError, OverflowError):
                    results.append({"name": p.name, "status": "invalid_manifest"})
        return results


def inspect_draft(value: str) -> dict:
    p = Path(value).expanduser()
    if not p.is_absolute():
        raise ValueError("Provide an absolute draft path")
    p = p.resolve(strict=True)
    if p.is_dir():
        p = next((p / n for n in ("draft_info.json", "draft_content.json") if (p / n).is_file()), p)
    if not p.is_file():
        raise ValueError("No draft_info.json or draft_content.json found")
    try:
        data = read_json(p)
    except ValueError as exc:
        if "NON_PLAINTEXT_DRAFT" in str(exc):
            return {"status": "unsupported_non_plaintext", "path": str(p), "readable": False,
                    "reason": "Encoded/encrypted or otherwise non-JSON draft. Source was not changed."}
        raise
    if not isinstance(data.get("tracks"), list) or not isinstance(data.get("materials"), dict):
        raise ValueError("JSON does not have a recognized draft timeline structure")
    tracks = []
    for t in data["tracks"]:
        clips = []
        for c in t.get("segments", []):
            timerange = c.get("target_timerange") or {}
            clips.append({"id": c.get("id"), "material_id": c.get("material_id"),
                          "start": timerange.get("start", 0) / 1_000_000,
                          "duration": timerange.get("duration", 0) / 1_000_000,
                          "speed": c.get("speed", 1), "volume": c.get("volume", 1)})
        tracks.append({"id": t.get("id"), "name": t.get("name"), "type": t.get("type"), "clips": clips})
    return {"status": "readable", "readable": True, "path": str(p), "native_app_verified": False,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "schema_version": data.get("version"),
            "app_version": data.get("platform", {}).get("app_version"),
            "platform": data.get("platform", {}).get("os"), "canvas": data.get("canvas_config"),
            "duration": data.get("duration", 0) / 1_000_000, "tracks": tracks,
            "materials": {k: len(v) for k, v in data["materials"].items() if isinstance(v, list) and v},
            "edit_support": "inspection_only; arbitrary native projects are not rewritten"}


def environment_status() -> dict:
    apps = []
    for parent in (Path("/Applications"), Path.home() / "Applications"):
        if not parent.is_dir():
            continue
        for path in parent.glob("*.app"):
            try:
                with (path / "Contents/Info.plist").open("rb") as f:
                    d = plistlib.load(f)
                if d.get("CFBundleIdentifier") not in {"com.lemon.lvpro", "com.lemon.lvoverseas"} and not any(word in path.name.lower() for word in ("jianying", "capcut", "剪映")):
                    continue
                apps.append({"path": str(path), "version": d.get("CFBundleShortVersionString"), "bundle_id": d.get("CFBundleIdentifier")})
            except (OSError, ValueError):
                continue
    root = Path.home() / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft"
    return {"version": __version__, "apps_in_standard_locations": apps, "draft_root_exists": root.is_dir(),
            "draft_root": str(root), "transport": "stdio", "network_uploads": False,
            "native_app_verified": False, "supports": ["local_media_metadata", "plaintext_draft_inspection", "new_drafts",
                    "managed_draft_revisions", "split_trim_move_volume", "srt_text", "self_contained_media",
                    "new_native_library_registration", "visual_transforms_crop_flip", "linear_visual_keyframes",
                    "motion_presets", "text_stroke_background_shadow", "audio_fades", "native_masks_mac_11",
                    "cached_native_animations_transitions", "native_resource_discovery", "batch_montage_reorder_ripple",
                    "baked_color_reverse_audio_processing", "extract_frame", "srt_import_export",
                    "single_commit_batch_edit", "compact_tool_results", "paged_project_read", "in_process_media_probe_cache"],
            "not_supported": ["encrypted_draft_reading", "arbitrary_native_draft_rewrite", "native_auto_export",
                    "cloud_ai_tools", "editable_hsl_curves_lut", "native_curve_speed", "native_volume_keyframes"],
            "validation_note": "See docs/features-v02.md and docs/verification-v02.md for per-feature native validation; environment detection alone does not validate a new draft."}
