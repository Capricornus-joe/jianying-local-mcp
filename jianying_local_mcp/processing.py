"""Bake a small, fixed set of effects into NEW local media files.

These operations do not create editable Jianying effect controls. Reuse the
returned path in a draft; the input file and existing output files are untouched.
No arbitrary FFmpeg options, filter strings, network inputs or models are used.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from .media import ffmpeg_path, probe_media

COLOR_RANGES = {
    "brightness": (-1.0, 1.0),
    "contrast": (0.0, 3.0),
    "saturation": (0.0, 3.0),
    "gamma": (0.1, 10.0),
}
BOOLEAN_OPERATIONS = {"reverse", "extract_audio", "normalize_audio", "denoise_audio"}
MAX_REVERSE_SECONDS = 600.0
LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"
DENOISE_FILTER = "afftdn=nf=-25:tn=1"


def _number(value: object, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return number


def _output_directory(value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("output_dir must be an absolute local directory")
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise ValueError("output_dir must be an absolute local directory")
    if raw.is_symlink():
        raise ValueError("output_dir must not be a symbolic link")
    directory = raw.resolve()
    # This also detects an existing file in a missing directory's ancestry.
    for ancestor in (directory, *directory.parents):
        if ancestor.exists() and not ancestor.is_dir():
            raise ValueError("output_dir and its existing parents must be directories")
    return directory


def _validate_operations(operations: dict, source: dict) -> dict:
    if not isinstance(operations, dict) or not operations:
        raise ValueError("operations must be a nonempty object of supported effects")
    unknown = set(operations) - COLOR_RANGES.keys() - BOOLEAN_OPERATIONS
    if unknown:
        raise ValueError("Unknown processing operations; arbitrary filters are not supported: "
                         + ", ".join(sorted(map(str, unknown))))
    normalized = {}
    for key, value in operations.items():
        if key in COLOR_RANGES:
            normalized[key] = _number(value, key, *COLOR_RANGES[key])
        else:
            if type(value) is not bool:
                raise ValueError(f"{key} must be a boolean")
            normalized[key] = value
    if not any(key in COLOR_RANGES or value for key, value in normalized.items()):
        raise ValueError("Choose at least one processing operation")
    has_color = bool(COLOR_RANGES.keys() & normalized.keys())
    if has_color and source["kind"] not in {"video", "image"}:
        raise ValueError("Color adjustments require video or image media")
    if normalized.get("reverse"):
        if source["kind"] != "video":
            raise ValueError("reverse requires video media")
        duration = source.get("duration")
        if duration is None or not 0 < duration <= MAX_REVERSE_SECONDS:
            raise ValueError("reverse requires a known video duration of at most 600 seconds")
    if any(normalized.get(key) for key in ("extract_audio", "normalize_audio", "denoise_audio")):
        if not source["has_audio"]:
            raise ValueError("The requested audio operation requires an audio stream")
    if normalized.get("extract_audio") and (has_color or normalized.get("reverse")):
        raise ValueError("extract_audio cannot be combined with video color adjustments or reverse")
    return normalized


def _filters(source: dict, operations: dict, output_kind: str) -> tuple[list[str], list[str]]:
    video, audio = [], []
    if operations.get("reverse"):
        video.append("reverse")
        if source["has_audio"]:
            audio.append("areverse")
    color = [f"{name}={operations[name]:.12g}" for name in COLOR_RANGES if name in operations]
    if color:
        video.append("eq=" + ":".join(color))
    if output_kind == "video":
        # H.264 4:2:0 requires even dimensions. At most one edge pixel is added.
        video.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")
    elif output_kind == "image":
        video.append("format=rgb24")
    if operations.get("denoise_audio"):
        audio.append(DENOISE_FILTER)
    if operations.get("normalize_audio"):
        audio.append(LOUDNORM_FILTER)
        # loudnorm internally changes sample rates. Rebuild continuous sample
        # timestamps while keeping the initial offset; otherwise some inputs
        # acquire a spurious trailing timestamp gap when muxed back into MP4.
        audio.append("asetpts=N/SR/TB+STARTPTS")
    return video, audio


def _command(source: dict, output: Path, output_kind: str,
             video_filters: list[str], audio_filters: list[str], frame_time: float | None) -> list[str]:
    command = [ffmpeg_path(), "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
               "-protocol_whitelist", "file,pipe", "-filter_threads", "2"]
    if frame_time is not None:
        command += ["-ss", f"{frame_time:.12g}"]
    command += ["-i", source["path"], "-map_metadata", "-1", "-map_chapters", "-1"]
    if output_kind in {"video", "image"}:
        # Capital V excludes attached album artwork from video selection.
        command += ["-map", "0:V:0"]
        if video_filters:
            command += ["-vf", ",".join(video_filters)]
        command += ["-metadata:s:v:0", "rotate=0"]
    if output_kind == "video":
        command += ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-threads", "2", "-movflags", "+faststart"]
    elif output_kind == "image":
        command += ["-an", "-frames:v", "1", "-c:v", "png", "-update", "1"]
    if output_kind != "image" and source["has_audio"]:
        command += ["-map", "0:a:0"]
        if audio_filters:
            command += ["-af", ",".join(audio_filters)]
        command += ["-ar", "48000"]
        if output_kind == "audio":
            command += ["-vn", "-c:a", "pcm_s16le"]
        else:
            command += ["-c:a", "aac", "-b:a", "192k"]
    command += ["-protocol_whitelist", "file,pipe", str(output)]
    return command


def _timeout(source: dict, frame_time: float | None) -> int:
    if frame_time is not None:
        return 120
    duration = source.get("duration")
    return max(120, min(3600, int(duration * 10 + 60))) if duration else 600


def _remove_own_link(final: Path, staged: Path) -> None:
    """Never delete a competing writer's file when rolling back a partial commit."""
    try:
        if not final.is_symlink() and os.path.samestat(final.stat(), staged.stat()):
            final.unlink()
    except FileNotFoundError:
        pass


def _run(source: dict, directory: Path, operations: dict, output_kind: str,
         dry_run: bool, frame_time: float | None = None) -> dict:
    video_filters, audio_filters = _filters(source, operations, output_kind)
    identifier = uuid.uuid4().hex
    suffix = {"video": ".mp4", "audio": ".wav", "image": ".png"}[output_kind]
    output_path = directory / f"processed_{identifier}{suffix}"
    record_path = directory / f"processed_{identifier}.processing.json"
    if output_path.exists() or output_path.is_symlink() or record_path.exists() or record_path.is_symlink():
        raise ValueError("Generated output path already exists; existing files are never replaced")
    result = {
        "status": "validated" if dry_run else "created", "dry_run": dry_run,
        "mode": "baked_media", "output_kind": output_kind,
        "output_path": str(output_path), "record_path": str(record_path),
        "source": source, "operations": operations,
        "effects_editable_in_jianying": False,
        "processing": {"video_filters": video_filters, "audio_filters": audio_filters,
                       "audio_sample_rate": 48000 if source["has_audio"] and output_kind != "image" else None,
                       "timeout_seconds": _timeout(source, frame_time)},
        "note": "Effects are baked into a new local file; reuse its path in create_draft. "
                "The source is unchanged. A dry-run path is a proposal; a real call chooses a new UUID.",
    }
    if frame_time is not None:
        result["source_time"] = frame_time
    if dry_run:
        return result
    directory.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".processing-", dir=directory))
    staged_output = staging / output_path.name
    staged_record = staging / record_path.name
    committed = []
    try:
        try:
            completed = subprocess.run(
                _command(source, staged_output, output_kind, video_filters, audio_filters, frame_time),
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=result["processing"]["timeout_seconds"], shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"Local media processing timed out after {result['processing']['timeout_seconds']} seconds") from exc
        except OSError as exc:
            raise ValueError(f"Could not start local FFmpeg: {exc.strerror or type(exc).__name__}") from exc
        if completed.returncode:
            raise ValueError("Local FFmpeg processing failed: " + completed.stderr.strip()[-2000:])
        if not staged_output.is_file() or staged_output.stat().st_size == 0:
            raise ValueError("FFmpeg produced no media; the requested frame may be beyond the decodable video")
        metadata = probe_media(str(staged_output))
        if metadata["kind"] != output_kind:
            raise ValueError("Processed output has an unexpected media type")
        if output_kind != "image" and not (metadata.get("duration") and metadata["duration"] > 0):
            raise ValueError("Processed output has no readable positive duration")
        metadata["path"] = str(output_path)
        result["output_metadata"] = metadata
        result["reuse_clip"] = {"kind": output_kind, "path": str(output_path), "start": 0}
        if output_kind != "image":
            result["reuse_clip"]["duration"] = metadata["duration"]
        else:
            result["note"] += " Choose a duration when placing this still image in a draft."
        record = {"format": "jianying-local-mcp-media-processing", "version": 1,
                  "created_at": datetime.now(timezone.utc).isoformat(), **result}
        with staged_record.open("x", encoding="utf-8") as output:
            json.dump(record, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        # Same-filesystem hard links are atomic and fail if ANY destination
        # already exists, unlike rename/replace, so UUID collisions cannot overwrite.
        for staged, final in ((staged_output, output_path), (staged_record, record_path)):
            os.link(staged, final)
            committed.append((final, staged))
        return result
    except BaseException:
        for final, staged in reversed(committed):
            _remove_own_link(final, staged)
        raise
    finally:
        shutil.rmtree(staging)


def process_media(path: str, output_dir: str, operations: dict, dry_run: bool = True) -> dict:
    """Create new local media with fixed color, reverse or audio processing.

    operations keys: brightness [-1,1], contrast/saturation [0,3], gamma
    [0.1,10], reverse, extract_audio, normalize_audio, denoise_audio (booleans).
    Reverse applies to both video and accompanying audio, with a 600s input cap.
    Loudness uses a one-pass -16 LUFS / -1.5 dBTP / LRA 11 target; silence and
    unusual dynamics may not reach it. Denoising uses FFmpeg afftdn, no model.
    Video outputs H.264/AAC MP4; audio outputs 48 kHz PCM WAV; images PNG.
    Effects are baked. Source files are not changed. dry_run writes nothing.
    """
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be a boolean")
    directory = _output_directory(output_dir)
    source = probe_media(path)
    normalized = _validate_operations(operations, source)
    output_kind = "audio" if normalized.get("extract_audio") else source["kind"]
    return _run(source, directory, normalized, output_kind, dry_run)


def extract_frame(path: str, time: float, output_dir: str, dry_run: bool = True) -> dict:
    """Extract a PNG at a video time in seconds. Use it as an image clip to freeze.

    This creates a new still image, not a native editable freeze-frame effect.
    The image's display duration is chosen later in the draft's image clip.
    """
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be a boolean")
    frame_time = _number(time, "time", 0, 86400 * 365)
    directory = _output_directory(output_dir)
    source = probe_media(path)
    if source["kind"] != "video":
        raise ValueError("extract_frame requires video media")
    duration = source.get("duration")
    if duration is not None and frame_time >= duration:
        raise ValueError("Frame time must be before the video duration")
    return _run(source, directory, {}, "image", dry_run, frame_time)
