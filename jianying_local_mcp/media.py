"""Read local media metadata without uploading files or invoking a shell."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
import os
from pathlib import Path
import re
import subprocess
from threading import Lock
from time import monotonic
import wave

EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts",
    ".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".aiff", ".aif",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp",
}
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# Cache metadata only, never media bytes or failed probes. A plan can contain
# 2000 clips; this bound also keeps repeated validation of large plans useful.
_PROBE_CACHE_LIMIT = 2048
_PROBE_CACHE_TTL = 300.0
_PROBE_CACHE: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
_PROBES_IN_FLIGHT: dict[tuple, Future] = {}
_PROBE_LOCK = Lock()


def _file_signature(path: Path) -> tuple:
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode)


def _clear_probe_cache() -> None:
    """Clear completed in-process entries (used by tests and local benchmarks)."""
    with _PROBE_LOCK:
        _PROBE_CACHE.clear()


def ffmpeg_path() -> str:
    custom = os.environ.get("JIANYING_FFMPEG")
    if custom:
        p = Path(custom).expanduser().resolve(strict=True)
        if not p.is_file() or not os.access(p, os.X_OK):
            raise ValueError("JIANYING_FFMPEG must point to an executable file")
        return str(p)
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def local_media_path(value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Provide an absolute local media path")
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise ValueError("Media paths must be absolute; network URLs are not supported")
    p = raw.resolve(strict=True)
    if not p.is_file() or p.suffix.lower() not in EXTENSIONS:
        raise ValueError("Unsupported local media file; playlists and network inputs are disabled")
    return p


def probe_media(value: str) -> dict:
    """Read metadata, reusing stable files for at most five minutes in-process.

    Every call revalidates the local path and file/executable stat identity.
    Concurrent requests for the same identity share one probe; different files
    can still be probed concurrently. Returned dictionaries are independent.
    No persistent cache is written, including during dry runs.
    """
    p = local_media_path(value)
    executable = ffmpeg_path()
    try:
        executable_signature = _file_signature(Path(executable))
    except OSError as exc:
        raise ValueError(f"Could not start the local FFmpeg executable: {exc.strerror or type(exc).__name__}") from exc
    key = (str(p), _file_signature(p), executable, executable_signature)
    with _PROBE_LOCK:
        cached = _PROBE_CACHE.get(key)
        if cached is not None:
            created, metadata = cached
            if monotonic() - created < _PROBE_CACHE_TTL:
                _PROBE_CACHE.move_to_end(key)
                return metadata.copy()
            del _PROBE_CACHE[key]
        pending = _PROBES_IN_FLIGHT.get(key)
        owner = pending is None
        if owner:
            pending = Future()
            _PROBES_IN_FLIGHT[key] = pending
    if not owner:
        return pending.result().copy()
    try:
        metadata = _probe_media_uncached(p, executable)
        if (_file_signature(p) != key[1]
                or _file_signature(Path(executable)) != executable_signature):
            raise ValueError("Media or FFmpeg changed during metadata read; retry with stable files")
        with _PROBE_LOCK:
            _PROBE_CACHE[key] = (monotonic(), metadata.copy())
            _PROBE_CACHE.move_to_end(key)
            while len(_PROBE_CACHE) > _PROBE_CACHE_LIMIT:
                _PROBE_CACHE.popitem(last=False)
        pending.set_result(metadata)
        return metadata.copy()
    except BaseException as exc:
        pending.set_exception(exc)
        raise
    finally:
        with _PROBE_LOCK:
            _PROBES_IN_FLIGHT.pop(key, None)


def _probe_media_uncached(p: Path, executable: str) -> dict:
    cmd = [executable, "-nostdin", "-hide_banner", "-protocol_whitelist", "file,pipe",
           "-i", str(p), "-t", "0", "-f", "null", "-"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Media metadata read timed out after 30 seconds") from exc
    except OSError as exc:
        raise ValueError(f"Could not start the local FFmpeg executable: {exc.strerror or type(exc).__name__}") from exc
    # Inspect input stream descriptions only, never output conversion settings.
    info = result.stderr.split("Stream mapping:")[0].split("Output #")[0]
    video_lines = [line for line in info.splitlines()
                   if re.search(r"Stream #0:\d+.*Video:", line)
                   and not re.search(r"\battached(?:_| )pic\b", line, re.IGNORECASE)]
    audio_lines = [line for line in info.splitlines() if re.search(r"Stream #0:\d+.*Audio:", line)]
    if result.returncode or not (video_lines or audio_lines):
        raise ValueError("FFmpeg could not read the local media file")
    width = height = 0
    fps = None
    codec = None
    if video_lines:
        line = video_lines[0]
        dimensions = re.search(r"(?:^|,\s)(\d{1,6})x(\d{1,6})(?:[ ,\[]|$)", line)
        if dimensions:
            width, height = map(int, dimensions.groups())
        frame_rate = re.search(r"([\d.]+) fps", line)
        fps = float(frame_rate.group(1)) if frame_rate else None
        codec_match = re.search(r"Video: ([^ ,]+)", line)
        codec = codec_match.group(1) if codec_match else None
    match = re.search(r"Duration: (\d+):(\d{2}):(\d{2}(?:\.\d+)?)", info)
    duration = sum(float(v) * unit for v, unit in zip(match.groups(), (3600, 60, 1))) if match else None
    # FFmpeg's diagnostic header rounds durations to centiseconds. PCM WAV
    # exposes the exact sample count, so preserve that more precise boundary.
    duration_precision = 0.01 if duration is not None else None
    if p.suffix.lower() == ".wav":
        try:
            with wave.open(str(p), "rb") as source:
                duration = source.getnframes() / source.getframerate()
                duration_precision = 1 / source.getframerate()
        except (wave.Error, EOFError, OSError):
            # The standard library cannot decode every WAV encoding; the
            # already validated FFmpeg metadata remains available in that case.
            pass
    rotation = re.search(r"rotation of (-?[\d.]+) degrees", info)
    return {"path": str(p), "bytes": p.stat().st_size,
            "kind": "image" if p.suffix.lower() in IMAGES else ("video" if video_lines else "audio"),
            "duration": duration, "duration_precision": duration_precision,
            "width": width, "height": height, "fps": fps,
            "has_audio": bool(audio_lines), "codec": codec,
            "rotation": float(rotation.group(1)) if rotation else 0.0}
