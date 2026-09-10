"""Useful editing workflows built on immutable, validated managed projects.

All mutations create a new revision through ProjectStore. Timeline arithmetic
uses the native schema's integer microseconds. No function edits a source
project, writes exports directly, or guesses unimplemented animation mappings.
"""

from __future__ import annotations

from copy import deepcopy
import re
from uuid import uuid4

from .core import ProjectStore, label, number, project_name


_US = 1_000_000
_MIN_CLIP_US = 1000
_STYLE_FIELDS = {"font_size", "color", "x", "y"}


def _us(value: float, field: str) -> int:
    return round(number(value, field, 0, 86400) * _US)


def _new_plan(store: ProjectStore, name: str, new_name: str) -> dict:
    plan = deepcopy(store.load_managed(name))
    plan["name"] = project_name(new_name)
    if name == new_name:
        raise ValueError("A workflow must use a new revision name")
    return plan


def _revision(store: ProjectStore, name: str, plan: dict, dry_run: bool) -> dict:
    result = store.create(plan, dry_run=dry_run)
    result["source_project_unchanged"] = name
    return result


def _ids(values: list[str], field: str) -> list[str]:
    if not isinstance(values, list) or not values or len(values) > 2000:
        raise ValueError(f"{field} must be a nonempty list of at most 2000 clip IDs")
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(f"{field} must contain nonempty strings")
    if len(set(values)) != len(values):
        raise ValueError(f"{field} cannot contain duplicate clip IDs")
    return values


def _require_static_mapping(clip: dict) -> None:
    fade = clip.get("audio_fade")
    nonzero_fade = any(fade.values()) if isinstance(fade, dict) else bool(fade)
    if clip.get("keyframes") or clip.get("animations") or nonzero_fade or clip.get("transition_out"):
        raise ValueError(
            f"Clip {clip['id']} has keyframes or animations, audio fades or a transition; "
            "this workflow cannot safely remap those effects after moving or trimming"
        )


def _transition_neighbors(clips: list[dict]) -> dict[str, str | None]:
    result = {}
    for track in {clip["track"] for clip in clips}:
        ordered = sorted((clip for clip in clips if clip["track"] == track), key=lambda clip: _us(clip["start"], "clip start"))
        for index, clip in enumerate(ordered):
            if clip.get("transition_out"):
                result[clip["id"]] = ordered[index + 1]["id"] if index + 1 < len(ordered) else None
    return result


def _check_transition_neighbors(original: dict[str, str | None], clips: list[dict]) -> None:
    for clip_id, new_neighbor in _transition_neighbors(clips).items():
        if original.get(clip_id) != new_neighbor:
            raise ValueError(f"Clip {clip_id} has a transition whose neighboring clip would change; remove it before this workflow")


def reorder_track(
    store: ProjectStore,
    name: str,
    new_name: str,
    track: str,
    clip_ids: list[str],
    start: float = 0,
    dry_run: bool = True,
) -> dict:
    """Order every clip of one track and close gaps, leaving other tracks intact.

    ``clip_ids`` must name each clip of the selected track exactly once. Source
    ranges, durations, speed and other properties are retained. ``start`` is
    the new start of the first clip in timeline seconds.
    """
    label(track, "track", 80)
    order = _ids(clip_ids, "clip_ids")
    cursor = _us(start, "start")
    plan = _new_plan(store, name, new_name)
    original_neighbors = _transition_neighbors(plan["clips"])
    selected = {clip["id"]: clip for clip in plan["clips"] if clip["track"] == track}
    if not selected or set(order) != set(selected):
        raise ValueError("clip_ids must cover every clip on the selected track exactly once")
    reordered = []
    for clip_id in order:
        clip = selected[clip_id]
        if _us(clip["start"], "clip start") != cursor:
            _require_static_mapping(clip)
        clip["start"] = cursor / _US
        cursor += _us(clip["duration"], "clip duration")
        reordered.append(clip)
    # Retain the track's original position in the plan, including layer order.
    first_index = next(index for index, clip in enumerate(plan["clips"]) if clip["track"] == track)
    untouched = [clip for clip in plan["clips"] if clip["track"] != track]
    insertion_index = sum(clip["track"] != track for clip in plan["clips"][:first_index])
    plan["clips"] = untouched[:insertion_index] + reordered + untouched[insertion_index:]
    _check_transition_neighbors(original_neighbors, plan["clips"])
    return _revision(store, name, plan, dry_run)


def _retained_piece(clip: dict, original_start: int, piece_start: int,
                    piece_end: int, new_start: int, fresh_id: bool) -> dict:
    if piece_end - piece_start < _MIN_CLIP_US:
        raise ValueError(f"Cut leaves a segment shorter than 1 ms in clip {clip['id']}; adjust the cut boundary")
    result = deepcopy(clip)
    if fresh_id:
        result["id"] = str(uuid4())
    result["start"] = new_start / _US
    result["duration"] = (piece_end - piece_start) / _US
    if clip["kind"] in {"video", "audio"}:
        advanced = (piece_start - original_start) / _US * clip.get("speed", 1)
        source_start = number(clip.get("source_start", 0), "source_start", 0, 86400)
        result["source_start"] = round((source_start + advanced) * _US) / _US
    else:
        result["source_start"] = 0
    return result


def ripple_delete(
    store: ProjectStore,
    name: str,
    new_name: str,
    start: float,
    end: float,
    dry_run: bool = True,
) -> dict:
    """Remove [start, end) from every track and shift later material left.

    Clips crossing both boundaries become two adjacent retained pieces. The
    right piece skips the deleted source material at the clip's own speed.
    Clips wholly inside the removed interval disappear. Cuts that would leave
    a nonempty piece shorter than 1 ms fail instead of silently discarding it.
    Keyframes, animations, nonzero audio fades and outgoing transitions on
    moved or trimmed clips are unsupported. Transition neighbors cannot change.
    """
    cut_start, cut_end = _us(start, "start"), _us(end, "end")
    if cut_end <= cut_start:
        raise ValueError("end must be greater than start at microsecond precision")
    plan = _new_plan(store, name, new_name)
    original_neighbors = _transition_neighbors(plan["clips"])
    timeline_end = max((_us(clip["start"], "clip start") + _us(clip["duration"], "clip duration")
                        for clip in plan["clips"]), default=0)
    if cut_end > timeline_end:
        raise ValueError("The deletion interval must lie within the project timeline")
    removed = cut_end - cut_start
    retained = []
    for clip in plan["clips"]:
        clip_start = _us(clip["start"], "clip start")
        clip_end = clip_start + _us(clip["duration"], "clip duration")
        if clip_end <= cut_start:
            retained.append(clip)
            continue
        if clip_start >= cut_end:
            _require_static_mapping(clip)
            clip["start"] = (clip_start - removed) / _US
            retained.append(clip)
            continue
        left = clip_start < cut_start
        right = clip_end > cut_end
        if not left and not right:
            continue
        _require_static_mapping(clip)
        if left:
            retained.append(_retained_piece(clip, clip_start, clip_start, cut_start, clip_start, False))
        if right:
            retained.append(_retained_piece(clip, clip_start, cut_end, clip_end, cut_start, left))
    plan["clips"] = retained
    _check_transition_neighbors(original_neighbors, plan["clips"])
    return _revision(store, name, plan, dry_run)


def style_subtitles(
    store: ProjectStore,
    name: str,
    new_name: str,
    style: dict,
    track: str | None = None,
    clip_ids: list[str] | None = None,
    dry_run: bool = True,
) -> dict:
    """Apply font_size/color/x/y to selected text clips in a new revision.

    With no selectors all text clips are styled. When both selectors are set,
    every requested ID must be a text clip on that track. Values are validated
    by ProjectStore and the native builder before anything is written.
    """
    if not isinstance(style, dict) or not style or set(style) - _STYLE_FIELDS:
        raise ValueError("style must contain only font_size, color, x and/or y")
    if track is not None:
        label(track, "track", 80)
    wanted = set(_ids(clip_ids, "clip_ids")) if clip_ids is not None else None
    plan = _new_plan(store, name, new_name)
    selected = [clip for clip in plan["clips"] if clip["kind"] == "text"
                and (track is None or clip["track"] == track)
                and (wanted is None or clip["id"] in wanted)]
    if not selected:
        raise ValueError("No subtitle clips match the selection")
    if wanted is not None and {clip["id"] for clip in selected} != wanted:
        raise ValueError("Every selected ID must refer to a text clip on the requested track")
    for clip in selected:
        clip.update(deepcopy(style))
    return _revision(store, name, plan, dry_run)


def _srt_time(microseconds: int) -> str:
    milliseconds = (microseconds + 500) // 1000
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def export_srt(store: ProjectStore, name: str, track: str | None = None) -> dict:
    """Return SRT content without creating a file or changing any project.

    Multiple text tracks can be combined; overlapping cues remain overlapping.
    Styling is omitted because SRT carries text and times. Text is literal,
    including markup. Blank lines inside text fail because they would become
    SRT block separators and prevent a faithful text round trip.
    """
    if track is not None:
        label(track, "track", 80)
    plan = store.load_managed(name)
    selected = [clip for clip in plan["clips"] if clip["kind"] == "text"
                and (track is None or clip["track"] == track)]
    if not selected:
        raise ValueError("No subtitle clips match the requested track")
    selected.sort(key=lambda clip: (_us(clip["start"], "clip start"), clip["track"], clip["id"]))
    blocks = []
    for index, clip in enumerate(selected, start=1):
        text = clip.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Subtitle {clip['id']} has no text")
        if any(not line.strip() for line in text.split("\n")) or "\r" in text:
            raise ValueError(f"Subtitle {clip['id']} contains blank lines or carriage returns that SRT cannot preserve")
        if re.search(r"(?m)^\s*[0-9]{2,}:[0-9]{2}:[0-9]{2}[,.][0-9]{1,3}\s*-->\s*"
                     r"[0-9]{2,}:[0-9]{2}:[0-9]{2}[,.][0-9]{1,3}\s*$", text):
            raise ValueError(f"Subtitle {clip['id']} contains a timing line that would be ambiguous in SRT")
        clip_start = _us(clip["start"], "clip start")
        clip_end = clip_start + _us(clip["duration"], "clip duration")
        blocks.append(f"{index}\n{_srt_time(clip_start)} --> {_srt_time(clip_end)}\n{text}")
    return {"name": name, "track": track, "cue_count": len(blocks), "content": "\n\n".join(blocks) + "\n"}


def montage_create(
    store: ProjectStore,
    name: str,
    paths: list[str],
    clip_duration: float | None = None,
    image_duration: float = 3,
    track: str = "主画面",
    width: int = 1920,
    height: int = 1080,
    fps: float = 30,
    dry_run: bool = True,
) -> dict:
    """Create an ordered video/image montage; audio-only inputs are rejected.

    Without clip_duration videos use their full measured duration and images
    use image_duration. A fixed clip_duration applies to both; videos shorter
    than it use their full duration. There is no looping or implicit speedup.
    """
    project_name(name)
    label(track, "track", 80)
    if not isinstance(paths, list) or not paths or len(paths) > 2000:
        raise ValueError("paths must be a nonempty list of at most 2000 local media paths")
    if any(not isinstance(path, str) or not path for path in paths):
        raise ValueError("paths must contain nonempty local media path strings")
    fixed = number(clip_duration, "clip_duration", 0.001, 86400) if clip_duration is not None else None
    image_duration = number(image_duration, "image_duration", 0.001, 86400)
    cache = {}
    clips = []
    cursor = 0
    for index, path in enumerate(paths):
        if path not in cache:
            cache[path] = store.probe(path)
        media = cache[path]
        kind = media.get("kind")
        if kind not in {"video", "image"}:
            raise ValueError(f"Media {index + 1} is not a video or image; audio-only inputs are not supported")
        if kind == "image":
            duration = fixed if fixed is not None else image_duration
        else:
            full_duration = number(media.get("duration"), f"Media {index + 1} duration", 0.001, 86400)
            duration = min(fixed, full_duration) if fixed is not None else full_duration
        duration_us = _us(duration, "clip duration")
        clips.append({"id": str(uuid4()), "kind": kind, "track": track,
                      "path": media["path"], "start": cursor / _US,
                      "duration": duration_us / _US, "source_start": 0, "speed": 1})
        cursor += duration_us
    return store.create({"name": name, "width": width, "height": height, "fps": fps, "clips": clips}, dry_run=dry_run)
