"""Strict, dependency-free SRT import into local text segments."""

from __future__ import annotations

import math
import re
import unicodedata
import uuid


_TIMESTAMP = r"([0-9]{2,}):([0-9]{2}):([0-9]{2})[,.]([0-9]{1,3})"
_TIMING_LINE = re.compile(rf"^[ \t]*{_TIMESTAMP}[ \t]*-->[ \t]*{_TIMESTAMP}[ \t]*$")
_INDEX_LINE = re.compile(r"^[0-9]+$")


def _finite_number(name: str, value: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _reject_controls(value: str, label: str) -> None:
    for character in value:
        if character not in "\n\t" and unicodedata.category(character) == "Cc":
            raise ValueError(f"{label} contains a forbidden control character U+{ord(character):04X}")


def _timestamp_ms(parts: tuple[str, ...], block_number: int) -> int:
    try:
        hours, minutes, seconds = (int(part) for part in parts[:3])
        milliseconds = int(parts[3].ljust(3, "0"))
    except ValueError as exc:
        raise ValueError(f"SRT block {block_number}: invalid timestamp") from exc
    if minutes > 59 or seconds > 59:
        raise ValueError(f"SRT block {block_number}: minutes and seconds must be between 00 and 59")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def parse_srt(
    content: str,
    track: str = "字幕",
    offset: float = 0,
    font_size: float = 48,
    color: str = "#FFFFFF",
    x: float = 0,
    y: float = -0.75,
) -> list[dict]:
    """Parse every SRT block, raising ``ValueError`` if any block is invalid.

    Cue numbers are optional. Timestamps accept comma or dot fractions of one
    to three digits and arbitrary nonnegative hours (including hours over 23).
    Blank lines separate cues. Text is retained literally, including markup;
    this function does not render or interpret HTML. Overlaps are preserved.
    All returned positions and times are finite, and starts are nonnegative.
    """
    if not isinstance(content, str):
        raise ValueError("SRT content must be a string")
    if not isinstance(track, str) or not track.strip():
        raise ValueError("track must be a nonempty string")
    if not isinstance(color, str):
        raise ValueError("color must be a string")
    _reject_controls(track, "track")
    _reject_controls(color, "color")
    offset = _finite_number("offset", offset)
    font_size = _finite_number("font_size", font_size)
    x = _finite_number("x", x)
    y = _finite_number("y", y)
    if font_size <= 0:
        raise ValueError("font_size must be positive")

    normalized = content.removeprefix("\ufeff").replace("\r\n", "\n")
    _reject_controls(normalized, "SRT content")
    blocks = [block for block in re.split(r"\n[ \t]*\n", normalized) if block.strip()]
    if not blocks:
        raise ValueError("SRT content is empty")

    segments: list[dict] = []
    for block_number, block in enumerate(blocks, start=1):
        lines = block.split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        timing_index = 1 if _INDEX_LINE.fullmatch(lines[0].strip()) else 0
        if len(lines) <= timing_index:
            raise ValueError(f"SRT block {block_number}: missing timing line")
        timing = _TIMING_LINE.fullmatch(lines[timing_index])
        if timing is None:
            raise ValueError(f"SRT block {block_number}: invalid timing line")
        text_lines = lines[timing_index + 1 :]
        if any(_TIMING_LINE.fullmatch(line) for line in text_lines):
            raise ValueError(f"SRT block {block_number}: missing blank line before another cue")
        subtitle_text = "\n".join(text_lines)
        if not subtitle_text.strip():
            raise ValueError(f"SRT block {block_number}: subtitle text is empty")

        start_ms = _timestamp_ms(timing.groups()[:4], block_number)
        end_ms = _timestamp_ms(timing.groups()[4:], block_number)
        if end_ms <= start_ms:
            raise ValueError(f"SRT block {block_number}: end must be greater than start")
        try:
            start = start_ms / 1000 + offset
            duration = (end_ms - start_ms) / 1000
        except OverflowError as exc:
            raise ValueError(f"SRT block {block_number}: timestamp is outside the supported numeric range") from exc
        if not math.isfinite(start) or not math.isfinite(duration) or not math.isfinite(start + duration):
            raise ValueError(f"SRT block {block_number}: resulting time must be finite")
        if start < 0:
            raise ValueError(f"SRT block {block_number}: offset makes the start negative")

        segments.append(
            {
                "id": str(uuid.uuid4()),
                "kind": "text",
                "track": track,
                "start": start,
                "duration": duration,
                "text": subtitle_text,
                "font_size": font_size,
                "color": color,
                "x": x,
                "y": y,
            }
        )
    return segments
