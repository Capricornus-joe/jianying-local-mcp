"""Decorate synthetic native segments with advanced properties and resolved resources.

Independent schema serializer. No app, cache, network, or media access occurs.
References and compatibility notes live in work/v02_github_research.md.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import PurePosixPath
import re
from typing import Callable


_PROPERTIES = {
    "x": "KFTypePositionX", "y": "KFTypePositionY",
    "scale_x": "KFTypeScaleX", "scale_y": "KFTypeScaleY",
    "rotation": "KFTypeRotation", "opacity": "KFTypeAlpha",
}
_TRANSFORM_FIELDS = set(_PROPERTIES) | {"flip_horizontal", "flip_vertical"}
_TEXT_FIELDS = {
    "bold", "italic", "underline", "alignment", "stroke_color", "stroke_width",
    "background_color", "background_opacity", "background_radius", "shadow_color",
    "shadow_opacity", "shadow_diffuse", "shadow_distance", "shadow_angle",
    "letter_spacing", "line_spacing",
}
_MASKS = {
    "circle": ("圆形", "circle", "6791700663249146381"),
    "rectangle": ("矩形", "rectangle", "6791700809454195207"),
    "linear": ("线性", "line", "6791652175668843016"),
}


def _num(value, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def _object(value, name: str, allowed: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(f"Unsupported {name} structure or fields")
    return value


def _rgb(value, name: str) -> list[float]:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError(f"{name} must be #RRGGBB")
    return [int(value[start:start + 2], 16) / 255 for start in (1, 3, 5)]


def _visual_value(prop: str, value) -> float:
    if prop == "opacity":
        return _num(value, prop, 0, 1)
    if prop in ("scale_x", "scale_y"):
        return _num(value, prop, 0.0001, 100)
    return _num(value, prop, -36000 if prop == "rotation" else -100,
                36000 if prop == "rotation" else 100)


def _transform(settings: dict, segment: dict) -> None:
    visual = segment.get("clip")
    if not isinstance(visual, dict):
        raise ValueError("Visual transform requires a visual native segment")
    for prop, value in settings.items():
        if prop.startswith("flip_"):
            if not isinstance(value, bool):
                raise ValueError(f"{prop} must be boolean")
            visual.setdefault("flip", {})[prop.removeprefix("flip_")] = value
        else:
            value = _visual_value(prop, value)
            if prop in ("x", "y"):
                visual.setdefault("transform", {})[prop] = value
            elif prop in ("scale_x", "scale_y"):
                visual.setdefault("scale", {})[prop[-1]] = value
            else:
                visual["alpha" if prop == "opacity" else prop] = value
    if "scale_x" in settings or "scale_y" in settings:
        segment["uniform_scale"] = {"on": False, "value": 1.0}


def _crop(settings: dict, material: dict) -> None:
    if set(settings) != {"left", "top", "right", "bottom"}:
        raise ValueError("crop requires left, top, right and bottom")
    edges = {key: _num(value, f"crop.{key}", 0, 1) for key, value in settings.items()}
    if edges["left"] >= edges["right"] or edges["top"] >= edges["bottom"]:
        raise ValueError("crop must enclose a nonempty rectangle")
    material["crop"] = {
        "upper_left_x": edges["left"], "upper_left_y": edges["top"],
        "upper_right_x": edges["right"], "upper_right_y": edges["top"],
        "lower_left_x": edges["left"], "lower_left_y": edges["bottom"],
        "lower_right_x": edges["right"], "lower_right_y": edges["bottom"],
    }
    material["crop_ratio"] = "free"
    material["crop_scale"] = 1.0


def _style_text(settings: dict, material: dict) -> None:
    try:
        content = json.loads(material["content"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Text material requires editable JSON content") from exc
    styles = content.get("styles") if isinstance(content, dict) else None
    if not isinstance(styles, list) or not styles or not all(isinstance(style, dict) for style in styles):
        raise ValueError("Text material has no supported style runs")
    for prop in ("bold", "italic", "underline"):
        if prop in settings:
            if not isinstance(settings[prop], bool):
                raise ValueError(f"{prop} must be boolean")
            for style in styles:
                style[prop] = settings[prop]
    if "alignment" in settings:
        alignment = settings["alignment"]
        if not isinstance(alignment, str) or alignment not in ("left", "center", "right"):
            raise ValueError("alignment must be left, center or right")
        material["alignment"] = {"left": 0, "center": 1, "right": 2}[alignment]
    check_flag = material.get("check_flag", 7)
    if not isinstance(check_flag, int) or isinstance(check_flag, bool):
        raise ValueError("Text check_flag must be an integer")
    if "stroke_color" in settings or "stroke_width" in settings:
        color = _rgb(settings.get("stroke_color", "#000000"), "stroke_color")
        width = _num(settings.get("stroke_width", 20), "stroke_width", 0, 100) / 500
        for style in styles:
            style["strokes"] = [{"width": width, "content": {"solid": {
                "alpha": 1.0, "color": color,
            }}}] if width else []
        check_flag = (check_flag | 8) if width else (check_flag & ~8)
    if any(key.startswith("background_") for key in settings):
        color = settings.get("background_color", "#000000")
        _rgb(color, "background_color")
        material.update({
            "background_style": 1, "background_color": color.upper(),
            "background_alpha": _num(settings.get("background_opacity", 1), "background_opacity", 0, 1),
            "background_round_radius": _num(settings.get("background_radius", 0), "background_radius", 0, 1),
            "background_height": 0.14, "background_width": 0.14,
            "background_horizontal_offset": 0.0, "background_vertical_offset": 0.0,
        })
        check_flag |= 16
    if any(key.startswith("shadow_") for key in settings):
        shadow = {
            "content": {"solid": {"color": _rgb(settings.get("shadow_color", "#000000"), "shadow_color")}},
            "alpha": _num(settings.get("shadow_opacity", 1), "shadow_opacity", 0, 1),
            "diffuse": _num(settings.get("shadow_diffuse", 15), "shadow_diffuse", 0, 100) / 600,
            "distance": _num(settings.get("shadow_distance", 5), "shadow_distance", 0, 1000),
            "angle": _num(settings.get("shadow_angle", -45), "shadow_angle", -360, 360),
        }
        for style in styles:
            style["shadows"] = [deepcopy(shadow)]
        check_flag |= 32
    if "letter_spacing" in settings:
        material["letter_spacing"] = _num(settings["letter_spacing"], "letter_spacing", -100, 100) * 0.05
    if "line_spacing" in settings:
        material["line_spacing"] = 0.02 + _num(settings["line_spacing"], "line_spacing", -100, 100) * 0.05
    material["check_flag"] = check_flag
    material["content"] = json.dumps(content, ensure_ascii=False, allow_nan=False)


def _keyframes(settings: dict, segment: dict, duration: float,
               clip_id: str, ident: Callable[[str], str]) -> None:
    existing = segment.get("common_keyframes", [])
    if not isinstance(existing, list) or not all(isinstance(item, dict) for item in existing):
        raise ValueError("common_keyframes must be a list")
    replacements = []
    for prop, points in settings.items():
        if not isinstance(points, list) or not 1 <= len(points) <= 2000:
            raise ValueError("Each keyframe property requires 1–2000 points")
        native_points = []
        times = set()
        for point in points:
            if not isinstance(point, dict) or set(point) != {"time", "value"}:
                raise ValueError("Keyframe points require only time and value; easing is not supported")
            offset = round(_num(point["time"], "keyframe time", 0, duration) * 1_000_000)
            if offset in times:
                raise ValueError("Keyframe times must be unique at microsecond precision")
            times.add(offset)
            value = _visual_value(prop, point["value"])
            native_points.append({
                "id": ident(f"advanced:keyframe:{clip_id}:{prop}:{offset}"),
                "time_offset": offset, "values": [value], "curveType": "Line",
                "graphID": "", "left_control": {"x": 0.0, "y": 0.0},
                "right_control": {"x": 0.0, "y": 0.0},
            })
        native_points.sort(key=lambda item: item["time_offset"])
        replacements.append({
            "id": ident(f"advanced:keyframe-list:{clip_id}:{prop}"),
            "material_id": "", "property_type": _PROPERTIES[prop],
            "keyframe_list": native_points,
        })
    replaced_types = {item["property_type"] for item in replacements}
    segment["common_keyframes"] = [item for item in existing if item.get("property_type") not in replaced_types] + replacements
    if set(settings) & {"scale_x", "scale_y"}:
        segment["uniform_scale"] = {"on": False, "value": 1.0}


def _mask(settings: dict, clip: dict, material: dict, mask_id: str) -> dict:
    settings = _object(settings, "mask", {
        "shape", "x", "y", "width", "height", "rotation", "feather", "invert", "round_corner",
    })
    shape = settings.get("shape")
    if not isinstance(shape, str) or shape not in _MASKS:
        raise ValueError("mask.shape must be circle, rectangle or linear")
    height = _num(settings.get("height", 0.5), "mask.height", 0.0001, 10)
    media_w = _num(material.get("width", clip.get("media_width")), "media_width", 1, 100000)
    media_h = _num(material.get("height", clip.get("media_height")), "media_height", 1, 100000)
    default_width = height if shape == "rectangle" else height * media_h / media_w
    width = _num(settings.get("width", default_width), "mask.width", 0.0001, 10)
    invert = settings.get("invert", False)
    if not isinstance(invert, bool):
        raise ValueError("mask.invert must be boolean")
    round_corner = _num(settings.get("round_corner", 0), "mask.round_corner", 0, 100)
    if shape != "rectangle" and round_corner:
        raise ValueError("Only rectangle masks support round_corner")
    name, resource_type, resource_id = _MASKS[shape]
    return {
        "id": mask_id, "type": "mask", "category": "video",
        "category_id": "", "category_name": "", "name": name, "platform": "all",
        "position_info": "", "resource_type": resource_type, "resource_id": resource_id,
        "config": {
            "aspectRatio": 1.0, "centerX": _num(settings.get("x", 0), "mask.x", -100, 100),
            "centerY": _num(settings.get("y", 0), "mask.y", -100, 100),
            "width": width, "height": height, "invert": invert,
            "rotation": _num(settings.get("rotation", 0), "mask.rotation", -36000, 36000),
            "feather": _num(settings.get("feather", 0), "mask.feather", 0, 100) / 100,
            "roundCorner": round_corner / 100,
        },
    }


def _resource(value: dict, kind: str, phase: str | None = None) -> dict:
    if not isinstance(value, dict):
        raise ValueError("resource must be a resolved resource object")
    if value.get("kind", kind) != kind:
        raise ValueError(f"Expected a {kind} resource")
    if phase and value.get("animation_type", phase) != phase:
        raise ValueError("Animation resource does not match the requested phase")
    out = {}
    for key in ("name", "effect_id", "resource_id"):
        item = value.get(key)
        if not isinstance(item, str) or not item or len(item) > 200 or any(ord(c) < 32 for c in item):
            raise ValueError(f"resource.{key} must be a nonempty string")
        out[key] = item
    path = value.get("path", "")
    if not isinstance(path, str) or "\x00" in path or (path and not PurePosixPath(path).is_absolute()):
        raise ValueError("resource.path must be an absolute local directory or empty")
    if value.get("cached") is False:
        raise ValueError("Requested resource is not cached; resolve it before building the draft")
    if value.get("ready_to_reference") is False:
        raise ValueError("Resource resolver has not approved this resource for referencing")
    out["path"] = path
    for key in ("category_id", "category_name"):
        item = value.get(key, "")
        if not isinstance(item, str):
            raise ValueError(f"resource.{key} must be a string")
        out[key] = item
    return out


def _animations(entries: list, clip: dict, duration: float, animation_id: str) -> dict:
    if not isinstance(entries, list) or not 1 <= len(entries) <= 3:
        raise ValueError("animations requires 1–3 animation records")
    native = []
    phases = set()
    total_edges = 0
    for entry in entries:
        entry = _object(entry, "animation", {"type", "duration", "resource"})
        phase = entry.get("type")
        if phase not in ("in", "out", "group") or phase in phases:
            raise ValueError("Animation phases must be unique in/out/group values")
        if phase == "group" and clip["kind"] == "text":
            raise ValueError("Text group/loop animations are not implemented")
        phases.add(phase)
        seconds = _num(entry.get("duration"), "animation duration", 0.000001, duration)
        if phase in ("in", "out"):
            total_edges += seconds
        is_text = clip["kind"] == "text"
        resource = _resource(entry.get("resource"), "text_animation" if is_text else "video_animation", phase)
        native.append({
            "id": resource["effect_id"], "resource_id": resource["resource_id"],
            "name": resource["name"], "type": phase,
            "start": round((duration - seconds if phase == "out" else 0) * 1_000_000),
            "duration": round(seconds * 1_000_000), "platform": "all",
            "material_type": "text" if is_text else "video", "panel": "" if is_text else "video",
            "path": resource["path"], "category_id": resource["category_id"],
            "category_name": resource["category_name"], "anim_adjust_params": None,
            "source_platform": 1, "request_id": "", "third_resource_id": "",
        })
    if ("group" in phases and len(phases) > 1) or total_edges > duration + 0.000001:
        raise ValueError("Group animations cannot combine with intro/outro; edge animations cannot overlap")
    return {"id": animation_id, "type": "sticker_animation",
            "multi_language_current": "none", "animations": native}


def _transition(entry: dict, duration: float, transition_id: str) -> dict:
    entry = _object(entry, "transition_out", {"duration", "resource"})
    resource = _resource(entry.get("resource"), "transition")
    overlap = entry["resource"].get("is_overlap")
    if not isinstance(overlap, bool):
        raise ValueError("Transition resource requires a verified boolean is_overlap")
    return {
        "id": transition_id, "type": "transition", "effect_id": resource["effect_id"],
        "resource_id": resource["resource_id"], "name": resource["name"],
        "duration": round(_num(entry.get("duration"), "transition duration", 0.000001, duration) * 1_000_000),
        "is_overlap": overlap, "path": resource["path"], "platform": "all",
        "category_id": resource["category_id"], "category_name": resource["category_name"],
    }


def apply_advanced(clip: dict, segment: dict, material: dict, materials: dict,
                   ident: Callable[[str], str]) -> None:
    """Apply transforms, text, linear keyframes, fades, masks and resolved resources.

    On validation failure, no passed object is changed. Crop belongs to a native
    material, so the caller must give a cropped clip its own material instance.
    Keyframe time is relative to the clip on the target timeline, in seconds.
    """
    active = {key for key in ("transform", "crop", "text_style", "keyframes", "audio_fade",
                             "mask", "animations", "transition_out") if key in clip}
    if not active:
        return
    clip_id = clip.get("id")
    if not isinstance(clip_id, str) or not clip_id:
        raise ValueError("Advanced properties require a clip id")
    kind = clip.get("kind")
    duration = _num(clip.get("duration"), "duration", 0.000001, 86400)
    visual = kind in ("video", "image", "text")
    if not visual and active & {"transform", "crop", "text_style", "keyframes", "mask", "animations", "transition_out"}:
        raise ValueError("Visual properties require video, image or text clips")
    updated_segment = deepcopy(segment)
    updated_material = deepcopy(material)
    pending_materials = []
    if "transform" in active:
        _transform(_object(clip["transform"], "transform", _TRANSFORM_FIELDS), updated_segment)
    if "crop" in active:
        if kind not in ("video", "image"):
            raise ValueError("crop requires video or image")
        _crop(_object(clip["crop"], "crop", {"left", "top", "right", "bottom"}), updated_material)
    if "text_style" in active:
        if kind != "text":
            raise ValueError("text_style requires text")
        _style_text(_object(clip["text_style"], "text_style", _TEXT_FIELDS), updated_material)
    if "keyframes" in active:
        _keyframes(_object(clip["keyframes"], "keyframes", set(_PROPERTIES)), updated_segment, duration, clip_id, ident)
    if "audio_fade" in active:
        if kind not in ("audio", "video") or (kind == "video" and not clip.get("has_audio", False)):
            raise ValueError("audio_fade requires an audio clip or a video with an audio stream")
        settings = _object(clip["audio_fade"], "audio_fade", {"in", "out"})
        fade_in = _num(settings.get("in", 0), "audio_fade.in", 0, duration)
        fade_out = _num(settings.get("out", 0), "audio_fade.out", 0, duration)
        if fade_in + fade_out > duration + 0.000001:
            raise ValueError("Audio fade durations cannot overlap")
        fade_id = ident(f"advanced:audio-fade:{clip_id}")
        fade = {
            "id": fade_id, "type": "audio_fade", "fade_type": 0,
            "fade_in_duration": round(fade_in * 1_000_000),
            "fade_out_duration": round(fade_out * 1_000_000),
        }
        refs = updated_segment.setdefault("extra_material_refs", [])
        if not isinstance(refs, list):
            raise ValueError("extra_material_refs must be a list")
        if fade_id not in refs:
            refs.append(fade_id)
        pending_materials.append(("audio_fades", fade))
    if "mask" in active:
        if kind not in ("video", "image"):
            raise ValueError("mask requires video or image")
        mask_id = ident(f"advanced:mask:{clip_id}")
        # This Mac build's own plaintext timeline template uses singular
        # common_mask. An app-authored public fixture also enables the segment.
        # The upstream version-only common_masks rule failed the local UI test.
        updated_segment["enable_video_mask"] = True
        pending_materials.append(("common_mask", _mask(clip["mask"], clip, updated_material, mask_id)))
    if "animations" in active:
        animation_id = ident(f"advanced:animation:{clip_id}")
        pending_materials.append(("material_animations", _animations(clip["animations"], clip, duration, animation_id)))
    if "transition_out" in active:
        if kind not in ("video", "image"):
            raise ValueError("transition_out requires video or image")
        transition_id = ident(f"advanced:transition:{clip_id}")
        pending_materials.append(("transitions", _transition(clip["transition_out"], duration, transition_id)))
    for group_name, new_material in pending_materials:
        group = materials.get(group_name, [])
        if not isinstance(group, list) or not all(isinstance(item, dict) for item in group):
            raise ValueError(f"{group_name} must be a list of material objects")
        refs = updated_segment.setdefault("extra_material_refs", [])
        if not isinstance(refs, list):
            raise ValueError("extra_material_refs must be a list")
        if new_material["id"] not in refs:
            refs.append(new_material["id"])
    # Commit only after every requested property has been validated.
    segment.clear()
    segment.update(updated_segment)
    material.clear()
    material.update(updated_material)
    for group_name, new_material in pending_materials:
        group = materials.setdefault(group_name, [])
        group[:] = [item for item in group if item.get("id") != new_material["id"]]
        group.append(new_material)
