"""Build a small, synthetic Mac Jianying draft without touching the filesystem.

This is an experimental serializer, not a claim of application compatibility.
No installed app, existing draft, account, or machine identifier is read here.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from uuid import UUID, uuid5


_MATERIAL_GROUPS = (
    "ai_translates audio_balances audio_effects audio_fades audio_track_indexes "
    "audios beats canvases chromas color_curves digital_humans drafts effects "
    "flowers green_screens handwrites hsl images log_color_wheels loudnesses "
    "manual_deformations masks material_animations material_colors "
    "multi_language_refs placeholders plugin_effects primary_color_wheels "
    "realtime_denoises shapes smart_crops smart_relights sound_channel_mappings "
    "speeds stickers tail_leaders text_templates texts time_marks transitions "
    "video_effects video_trackings videos vocal_beautifys vocal_separations"
).split()
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
# Still-image source metadata follows pyJianYingDraft's three-hour convention.
# Segment timeranges remain the actual edit length; native playback is verified
# separately rather than treating this convention as a documented requirement.
_IMAGE_MATERIAL_MIN_DURATION_US = 10_800_000_000


def validate_display_name(value: object) -> str:
    """Validate a visible media label without changing its spelling."""
    if not isinstance(value, str) or not value.strip() or not 1 <= len(value) <= 120:
        raise ValueError("display_name must be a non-empty string of 1–120 characters")
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value):
        raise ValueError("display_name contains control or invalid characters")
    return value


def _number(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        raise ValueError(f"{label} must be finite and {'positive' if positive else 'nonnegative'}")
    return number


def _us(value: object, label: str, *, positive: bool = False) -> int:
    number = _number(value, label, positive=positive)
    if number > (2**63 - 1) / 1_000_000:
        raise ValueError(f"{label} exceeds the native timerange limit")
    result = round(number * 1_000_000)
    if positive and result < 1:
        raise ValueError(f"{label} is shorter than one microsecond")
    return result


def _dimension(value: object, label: str) -> int:
    number = _number(value, label, positive=True)
    if number != int(number):
        raise ValueError(f"{label} must be an integer")
    return int(number)


def _position(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{label} must be a number between -1 and 1")
    if not math.isfinite(value) or not -1 <= value <= 1:
        raise ValueError(f"{label} must be between -1 and 1")
    return float(value)


def _platform() -> dict:
    return {
        "app_id": 3704, "app_source": "lv", "app_version": "11.4.0",
        "os": "mac", "os_version": "", "device_id": "",
        "hard_disk_id": "", "mac_address": "",
    }


def _visual_material(clip: dict, material_id: str, duration: int) -> dict:
    image = clip["kind"] == "image"
    return {
        "id": material_id, "type": "photo" if image else "video",
        "path": clip["path"], "material_name": clip.get("display_name", Path(clip["path"]).name),
        "duration": duration, "width": clip["media_width"],
        "height": clip["media_height"],
        "has_audio": False if image else bool(clip.get("has_audio", False)),
        "check_flag": 63487, "local_material_id": "", "local_id": "",
        "material_id": material_id, "origin_material_id": "", "material_url": "",
        "media_path": "", "source": 0, "source_platform": 0,
        "category_id": "", "category_name": "", "team_id": "",
        "request_id": "", "formula_id": "", "picture_from": "none",
        "picture_set_category_id": "", "picture_set_category_name": "",
        "aigc_type": "none", "aigc_item_id": "", "aigc_history_id": "",
        "audio_fade": None, "cartoon_path": "", "freeze": None,
        "crop": {
            "upper_left_x": 0.0, "upper_left_y": 0.0,
            "upper_right_x": 1.0, "upper_right_y": 0.0,
            "lower_left_x": 0.0, "lower_left_y": 1.0,
            "lower_right_x": 1.0, "lower_right_y": 1.0,
        },
        "crop_ratio": "free", "crop_scale": 1.0, "extra_type_option": 0,
        "is_ai_generate_content": False, "is_copyright": False,
        "is_text_edit_overdub": False, "is_unified_beauty_mode": False,
        "intensifies_path": "", "intensifies_audio_path": "",
        "reverse_path": "", "reverse_intensifies_path": "",
        "object_locked": None, "smart_motion": None,
        "matting": {
            "flag": 0, "has_use_quick_brush": False,
            "has_use_quick_eraser": False, "interactiveTime": [],
            "path": "", "strokes": [],
        },
        "stable": {
            "matrix_path": "", "stable_level": 0,
            "time_range": {"start": 0, "duration": 0},
        },
        "video_algorithm": {
            "algorithms": [], "complement_frame_config": None,
            "deflicker": None, "gameplay_configs": [],
            "motion_blur_config": None, "noise_reduction": None,
            "path": "", "quality_enhance": None, "time_range": None,
        },
    }


def _audio_material(clip: dict, material_id: str, duration: int) -> dict:
    material = dict.fromkeys((
        "aigc_history_id aigc_item_id category_id category_name effect_id "
        "formula_id intensifies_path local_material_id music_id query "
        "request_id resource_id search_id source_from team_id text_id "
        "tone_category_id tone_category_name tone_effect_id tone_effect_name "
        "tone_platform tone_second_category_id tone_second_category_name "
        "tone_speaker tone_type video_id"
    ).split(), "")
    material.update({
        "id": material_id, "type": "extract_music", "app_id": 0,
        "path": clip["path"], "name": clip.get("display_name", Path(clip["path"]).name),
        "duration": duration, "check_flag": 1, "source_platform": 0,
        "copyright_limit_type": "none", "is_ai_clone_tone": False,
        "is_text_edit_overdub": False, "is_ugc": False, "wave_points": [],
    })
    return material


def _text_material(clip: dict, material_id: str) -> dict:
    content = clip["text"]
    if not isinstance(content, str) or not content:
        raise ValueError("text must be a nonempty string")
    color = clip.get("color", "#FFFFFF")
    if not isinstance(color, str) or not _HEX_COLOR.fullmatch(color):
        raise ValueError("color must be #RRGGBB")
    # Plan sizes are pixels; 48 px maps to the community schema's size 8.
    # This initial calibration still needs a native application visual check.
    size = _number(clip.get("font_size", 48), "font_size", positive=True) / 6
    rgb = [int(color[offset:offset + 2], 16) / 255 for offset in (1, 3, 5)]
    style = {
        "range": [0, len(content.encode('utf-16-le')) // 2], "size": size,
        "bold": False, "italic": False, "underline": False, "strokes": [],
        "fill": {"alpha": 1.0, "content": {
            "render_type": "solid", "solid": {"alpha": 1.0, "color": rgb},
        }},
    }
    return {
        "id": material_id, "type": "text", "check_flag": 7,
        "content": json.dumps({"text": content, "styles": [style]}, ensure_ascii=False),
        "alignment": 1, "typesetting": 0, "global_alpha": 1.0,
        "letter_spacing": 0.0, "line_spacing": 0.02,
        "line_feed": 1, "line_max_width": 0.82,
        "force_apply_line_max_width": False,
    }


def _segment(clip: dict, segment_id: str, material_id: str,
             refs: list[str], render_index: int) -> dict:
    kind = clip["kind"]
    is_audio = kind == "audio"
    visual = None if is_audio else {
        "alpha": 1.0, "flip": {"horizontal": False, "vertical": False},
        "rotation": 0.0, "scale": {"x": 1.0, "y": 1.0},
        "transform": {
            "x": _position(clip.get("x", 0), "x"),
            "y": _position(clip.get("y", -0.75 if kind == "text" else 0), "y"),
        },
    }
    volume = _number(clip.get("volume", 1), "volume")
    source = None if kind == "text" else {
        "start": clip["_source_start_us"], "duration": clip["_source_duration_us"],
    }
    return {
        "id": segment_id, "material_id": material_id, "extra_material_refs": refs,
        "source_timerange": source,
        "target_timerange": {"start": clip["_start_us"], "duration": clip["_duration_us"]},
        "speed": clip["_speed"], "volume": volume,
        "last_nonzero_volume": volume if volume else 1.0,
        "clip": visual, "visible": True, "reverse": False,
        "track_attribute": 0, "track_render_index": render_index,
        "render_index": render_index,
        "caption_info": None, "cartoon": False, "group_id": "",
        "common_keyframes": [], "keyframe_refs": [], "intensifies_audio": False,
        "is_placeholder": False, "is_tone_modify": False,
        "enable_adjust": kind in ("video", "image"),
        "enable_lut": kind in ("video", "image"),
        "enable_color_correct_adjust": False, "enable_color_curves": True,
        "enable_color_match_adjust": False, "enable_color_wheels": True,
        "enable_smart_color_adjust": False,
        "hdr_settings": None if is_audio else {"intensity": 1.0, "mode": 1, "nits": 1000},
        "uniform_scale": None if is_audio else {"on": True, "value": 1.0},
        "template_id": "", "template_scene": "default",
        "responsive_layout": {
            "enable": False, "horizontal_pos_layout": 0, "size_layout": 0,
            "target_follow": "", "vertical_pos_layout": 0,
        },
    }


def build_native(plan: dict, project_dir: Path) -> dict[str, dict]:
    """Return draft_info.json and draft_meta_info.json; do not read or write files.

    Media paths must already be absolute final paths, preferably inside the
    caller's bundled Resources directory. The caller handles probing, copying,
    staged writes, registration, app checks, and any eventual native export.
    Duration is the target timeline duration; a source uses duration * speed.
    """
    project_uuid = UUID(plan["id"])
    project_id = str(project_uuid).upper()
    project_dir = Path(project_dir)
    if not project_dir.is_absolute():
        raise ValueError("project_dir must be absolute")
    if not isinstance(plan["name"], str) or not plan["name"].strip():
        raise ValueError("name must be a nonempty string")
    width = _dimension(plan["width"], "width")
    height = _dimension(plan["height"], "height")
    fps = _number(plan["fps"], "fps", positive=True)
    materials = {group: [] for group in _MATERIAL_GROUPS}
    tracks: dict[tuple[str, str], dict] = {}
    media: dict[tuple, dict] = {}
    registry = []
    seen_clip_ids: set[str] = set()
    duration = 0

    def ident(label: str) -> str:
        return str(uuid5(project_uuid, label)).upper()

    for original in plan["clips"]:
        clip = dict(original)
        clip_id = clip["id"]
        if not isinstance(clip_id, str) or not clip_id or clip_id in seen_clip_ids:
            raise ValueError("clip ids must be nonempty and unique")
        seen_clip_ids.add(clip_id)
        kind = clip["kind"]
        if kind not in ("video", "audio", "image", "text"):
            raise ValueError(f"unsupported clip kind: {kind}")
        if "display_name" in clip:
            if kind == "text":
                raise ValueError("display_name is only supported for video, image and audio clips")
            validate_display_name(clip["display_name"])
        track_name = clip["track"]
        if not isinstance(track_name, str) or not track_name:
            raise ValueError("track must be a nonempty string")
        track_type = "video" if kind == "image" else kind
        if any(name == track_name and t != track_type for t, name in tracks):
            raise ValueError("a track cannot mix audio, visual, or text clips")
        track_key = (track_type, track_name)
        if track_key not in tracks:
            tracks[track_key] = {
                "id": ident(f"track:{track_type}:{track_name}"), "type": track_type,
                "name": track_name, "is_default_name": False,
                "attribute": 0, "flag": 0, "segments": [],
            }
        clip["_start_us"] = _us(clip["start"], "start")
        clip["_duration_us"] = _us(clip["duration"], "duration", positive=True)
        clip["_source_start_us"] = _us(clip.get("source_start", 0), "source_start")
        clip["_speed"] = _number(clip.get("speed", 1), "speed", positive=True)
        clip["_source_duration_us"] = _us(
            clip["duration"] * clip["_speed"], "source duration", positive=True)
        if kind in ("image", "text") and (
                clip["_source_start_us"] or clip["_speed"] != 1):
            raise ValueError("image/text clips require source_start=0 and speed=1")
        duration = max(duration, clip["_start_us"] + clip["_duration_us"])
        refs = []
        if kind == "text":
            material_id = ident(f"text:{clip_id}")
            material = _text_material(clip, material_id)
            materials["texts"].append(material)
        else:
            path = clip["path"]
            if not isinstance(path, str) or "\x00" in path or not Path(path).is_absolute():
                raise ValueError("media path must be an absolute local path")
            material_duration = _us(clip.get("media_duration", 0), "media_duration")
            source_end = clip["_source_start_us"] + clip["_source_duration_us"]
            if kind == "image":
                material_duration = max(material_duration, _IMAGE_MATERIAL_MIN_DURATION_US)
            # FFmpeg's container duration display rounds to centiseconds.
            # Match the normalizer's half-centisecond allowance plus 1us.
            if kind != "image" and source_end > material_duration + 5001:
                raise ValueError("clip source range exceeds media duration")
            if kind in ("video", "image"):
                clip["media_width"] = _dimension(clip["media_width"], "media_width")
                clip["media_height"] = _dimension(clip["media_height"], "media_height")
            else:
                clip["media_width"] = clip["media_height"] = 0
            crop_tag = json.dumps(clip.get('crop'), sort_keys=True) if clip.get('crop') else ''
            material_tag = f'{kind}:{path}' + (f':crop:{crop_tag}' if crop_tag else '')
            display_name = clip.get("display_name", Path(path).name)
            # Labels belong to native materials, so differently named uses need
            # separate records while still referencing the same bundled file.
            if display_name != Path(path).name:
                material_tag += ':display_name:' + json.dumps(display_name, ensure_ascii=False)
            material_key = (kind, path, crop_tag, display_name)
            if material_key not in media:
                material_id = ident(f"media:{material_tag}")
                material_duration = max(material_duration, source_end)
                material = (_audio_material if kind == "audio" else _visual_material)(
                    clip, material_id, material_duration)
                media[material_key] = material
                materials["audios" if kind == "audio" else "videos"].append(material)
                registry.append({
                    "id": ident(f"registry:{material_tag}"), "type": 0,
                    "metetype": {"video": "video", "image": "photo", "audio": "music"}[kind],
                    "file_Path": path, "extra_info": display_name,
                    "width": clip["media_width"], "height": clip["media_height"],
                    "duration": material_duration, "create_time": 0,
                    "import_time": 0, "import_time_ms": 0, "item_source": 1,
                    "md5": "", "roughcut_time_range": {"start": -1, "duration": -1},
                    "sub_time_range": {"start": -1, "duration": -1},
                })
            else:
                material = media[material_key]
                material_id = material["id"]
                if kind != "image" and abs(material["duration"] - material_duration) > 5001:
                    raise ValueError("repeated media must have consistent duration metadata")
                if kind in ("video", "image") and any(
                        material[key] != clip[f"media_{key}"] for key in ("width", "height")):
                    raise ValueError("repeated media must have consistent dimensions")
                if source_end > material["duration"]:
                    material["duration"] = source_end
                    next(r for r in registry if r['id'] == ident(f'registry:{material_tag}'))['duration'] = source_end
            speed_id = ident(f"speed:{clip_id}")
            materials["speeds"].append({
                "id": speed_id, "type": "speed", "mode": 0,
                "speed": clip["_speed"], "curve_speed": None,
            })
            refs.append(speed_id)
            if kind != "image":
                channel_id = ident(f"channel:{clip_id}")
                vocal_id = ident(f"vocal:{clip_id}")
                materials["sound_channel_mappings"].append({
                    "id": channel_id, "type": "none", "audio_channel_mapping": 0,
                    "is_config_open": False,
                })
                materials["vocal_separations"].append({
                    "id": vocal_id, "type": "vocal_separation", "choice": 0,
                    "production_path": "", "time_range": None,
                })
                refs.extend((channel_id, vocal_id))
            if kind in ("video", "image"):
                canvas_id = ident(f"canvas:{clip_id}")
                materials["canvases"].append({
                    "id": canvas_id, "type": "canvas_color", "color": "",
                    "blur": 0.0, "album_image": "", "image": "", "image_id": "",
                    "image_name": "", "team_id": "", "source_platform": 0,
                })
                refs.append(canvas_id)
        segment = _segment(clip, ident(f"segment:{clip_id}"), material_id, refs, 0)
        from .advanced_native import apply_advanced
        apply_advanced(clip, segment, material, materials, ident)
        tracks[track_key]["segments"].append(segment)

    ordered_tracks = sorted(tracks.values(), key=lambda track: {
        "video": 0, "audio": 1, "text": 2,
    }[track["type"]])
    visual_index = 0
    for track in ordered_tracks:
        track["segments"].sort(key=lambda segment: segment["target_timerange"]["start"])
        previous_end = -1
        for segment in track["segments"]:
            timing = segment["target_timerange"]
            if timing["start"] < previous_end:
                raise ValueError("clips overlap on the same track")
            previous_end = timing["start"] + timing["duration"]
            layer = 14000 + visual_index if track["type"] == "text" else visual_index
            segment["render_index"] = 0 if track["type"] == "audio" else layer
            segment["track_render_index"] = segment["render_index"]
        if track["type"] != "audio":
            if track["type"] == "video" and visual_index:
                track["flag"] = 2
            visual_index += 1

    info = {
        "id": project_id, "name": plan["name"], "version": 360000,
        "new_version": "112.0.0", "source": "default", "duration": duration,
        "fps": fps, "color_space": 0, "create_time": 0, "update_time": 0,
        "canvas_config": {"width": width, "height": height, "ratio": "original", "background": None},
        "materials": materials, "tracks": ordered_tracks,
        "platform": _platform(), "last_modified_platform": _platform(),
        "keyframes": {name: [] for name in (
            "adjusts", "audios", "effects", "filters", "handwrites", "stickers", "texts", "videos")},
        "keyframe_graph_list": [], "relationships": [],
        "render_index_track_mode_on": False, "free_render_index_mode_on": False,
        "static_cover_image_path": "", "cover": None, "retouch_cover": None,
        "extra_info": None, "group_container": None, "mutable_config": None,
        "time_marks": None,
        "config": {
            "maintrack_adsorb": False, "material_save_mode": 0, "video_mute": False,
            "adjust_max_index": 1, "combination_max_index": 1, "sticker_max_index": 1,
            "extract_audio_last_index": 1, "record_audio_last_index": 1,
            "original_sound_last_index": 1, "attachment_info": [],
            "export_range": None, "lyrics_recognition_id": "", "lyrics_sync": True,
            "lyrics_taskinfo": [], "subtitle_recognition_id": "", "subtitle_sync": True,
            "subtitle_taskinfo": [], "subtitle_keywords_config": None,
            "system_font_list": [], "zoom_info_params": None,
        },
    }
    meta = {
        "draft_id": project_id, "draft_name": plan["name"],
        "draft_fold_path": str(project_dir), "draft_root_path": str(project_dir.parent),
        "draft_cover": "", "draft_type": "", "draft_new_version": "",
        "draft_is_invisible": False, "draft_is_from_deeplink": "false",
        "draft_is_ai_packaging_used": False, "draft_is_ai_shorts": False,
        "draft_is_article_video_draft": False,
        "draft_materials": [{"type": group, "value": registry if group == 0 else []}
                            for group in range(8)],
        "draft_materials_copied_info": [], "draft_segment_extra_info": [],
        "draft_timeline_materials_size_": 0, "draft_removable_storage_device": "",
        "draft_cloud_materials": [], "draft_cloud_last_action_download": False,
        "draft_deeplink_url": "", "draft_cloud_purchase_info": "",
        "draft_cloud_capcut_purchase_info": "", "draft_cloud_videocut_purchase_info": "",
        "draft_cloud_template_id": "", "draft_cloud_tutorial_info": "",
        "cloud_package_completed_time": "", "tm_draft_cloud_completed": "",
        "tm_draft_cloud_modified": 0, "tm_draft_create": 0,
        "tm_draft_modified": 0, "tm_draft_removed": 0, "tm_duration": duration,
        "draft_enterprise_info": {
            "draft_enterprise_extra": "", "draft_enterprise_id": "",
            "draft_enterprise_name": "", "enterprise_material": [],
        },
    }
    return {"draft_info.json": info, "draft_meta_info.json": meta}
