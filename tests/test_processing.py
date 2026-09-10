"""Actual synthetic-media checks plus no-write, validation and failure cases."""
from array import array
import hashlib
import json
import math
from pathlib import Path
import subprocess
import uuid
import wave

import pytest

from jianying_local_mcp import processing
from jianying_local_mcp.core import ProjectStore
from jianying_local_mcp.media import ffmpeg_path, probe_media


@pytest.fixture(scope="module")
def synthetic_video(tmp_path_factory):
    directory = tmp_path_factory.mktemp("processing-media")
    video = directory / "十秒合成素材.mp4"
    subprocess.run([
        ffmpeg_path(), "-nostdin", "-v", "error", "-n",
        "-f", "lavfi", "-i", "color=c=red:s=160x120:r=10:d=5",
        "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=10:d=5",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=10",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-map", "2:a", "-af", "volume=0.08",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video),
    ], check=True, capture_output=True, timeout=60)
    assert probe_media(str(video))["duration"] == pytest.approx(10, abs=0.01)
    return video


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixel(path, time=0):
    result = subprocess.run([
        ffmpeg_path(), "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-ss", str(time), "-i", str(path), "-frames:v", "1", "-vf", "scale=1:1",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ], check=True, capture_output=True, timeout=30)
    assert len(result.stdout) == 3
    return tuple(result.stdout)


def wav_rms(path):
    with wave.open(str(path), "rb") as source:
        assert source.getsampwidth() == 2
        samples = array("h", source.readframes(source.getnframes()))
        return math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768


def test_dry_run_validates_real_input_and_never_creates_output(synthetic_video, tmp_path):
    output_dir = tmp_path / "未创建" / "输出素材"
    source_hash = digest(synthetic_video)
    operations = {"brightness": 0.1, "contrast": 1.2, "reverse": True, "normalize_audio": True}
    before = operations.copy()
    result = processing.process_media(str(synthetic_video), str(output_dir), operations)
    assert result["status"] == "validated"
    assert result["dry_run"] is True
    assert result["mode"] == "baked_media"
    assert result["effects_editable_in_jianying"] is False
    assert Path(result["output_path"]).parent == output_dir
    assert result["output_kind"] == "video"
    assert result["processing"]["audio_filters"] == ["areverse", processing.LOUDNORM_FILTER,
                                                     "asetpts=N/SR/TB+STARTPTS"]
    assert not (tmp_path / "未创建").exists()
    assert digest(synthetic_video) == source_hash
    assert operations == before
    frame = processing.extract_frame(str(synthetic_video), 7, str(output_dir))
    assert frame["source_time"] == 7
    assert frame["output_kind"] == "image"
    assert not output_dir.exists()


def test_actual_color_reverse_audio_and_draft_reuse(synthetic_video, tmp_path):
    before = digest(synthetic_video)
    operations = {"brightness": 0.08, "contrast": 1.15, "saturation": 0.8, "gamma": 1.1,
                  "reverse": True, "normalize_audio": True, "denoise_audio": True}
    result = processing.process_media(str(synthetic_video), str(tmp_path / "processed"), operations, False)
    output = Path(result["output_path"])
    assert result["status"] == "created"
    assert output.is_file()
    assert digest(synthetic_video) == before
    metadata = result["output_metadata"]
    assert metadata["path"] == str(output)
    assert (metadata["kind"], metadata["width"], metadata["height"], metadata["has_audio"]) == ("video", 160, 120, True)
    assert metadata["duration"] == pytest.approx(10, abs=0.04)
    first, last = pixel(output, 1), pixel(output, 8)
    assert first[2] > first[0] + 50  # Blue second half now comes first.
    assert last[0] > last[2] + 50   # Red first half now comes last.
    assert first[1] > pixel(synthetic_video, 8)[1] + 5  # The color change was rendered.
    record = json.loads(Path(result["record_path"]).read_text())
    assert record["format"] == "jianying-local-mcp-media-processing"
    assert record["operations"] == operations
    assert record["output_path"] == str(output)
    assert record["source"]["path"] == str(synthetic_video)
    assert not list(output.parent.glob(".processing-*"))
    created = ProjectStore(tmp_path / "drafts").create(
        {"name": "预处理素材复用", "clips": [result["reuse_clip"]]}, dry_run=False)
    assert created["status"] == "created"


def test_actual_audio_extraction_normalization_and_denoising(synthetic_video, tmp_path):
    plain = processing.process_media(str(synthetic_video), str(tmp_path), {"extract_audio": True}, False)
    clean = processing.process_media(str(synthetic_video), str(tmp_path),
        {"extract_audio": True, "normalize_audio": True, "denoise_audio": True}, False)
    assert plain["output_kind"] == clean["output_kind"] == "audio"
    for result in (plain, clean):
        with wave.open(result["output_path"], "rb") as source:
            assert source.getframerate() == 48000
            assert source.getnframes() / source.getframerate() == pytest.approx(10, abs=0.04)
    assert wav_rms(clean["output_path"]) > wav_rms(plain["output_path"]) * 3
    # Audio-only input is also processed; a separate output is created.
    converted = processing.process_media(plain["output_path"], str(tmp_path), {"normalize_audio": True}, False)
    assert converted["output_path"] not in (plain["output_path"], clean["output_path"])
    assert converted["output_metadata"]["kind"] == "audio"


def test_actual_frame_extract_and_image_color(synthetic_video, tmp_path):
    frame = processing.extract_frame(str(synthetic_video), 7, str(tmp_path), False)
    path = Path(frame["output_path"])
    assert path.suffix == ".png"
    assert frame["output_metadata"]["kind"] == "image"
    assert frame["reuse_clip"] == {"kind": "image", "path": str(path), "start": 0}
    rgb = pixel(path)
    assert rgb[2] > rgb[0] + 100
    colored = processing.process_media(str(path), str(tmp_path), {"brightness": 0.2}, False)
    assert colored["output_kind"] == "image"
    assert pixel(Path(colored["output_path"]))[1] > rgb[1] + 20
    assert json.loads(Path(frame["record_path"]).read_text())["source_time"] == 7


@pytest.fixture
def stub_source(monkeypatch, tmp_path):
    source = {"path": str(tmp_path / "source.mp4"), "bytes": 1, "kind": "video", "duration": 10,
              "duration_precision": 0.01, "width": 160, "height": 120, "fps": 10,
              "has_audio": True, "codec": "h264", "rotation": 0}
    monkeypatch.setattr(processing, "probe_media", lambda path: source.copy())
    return source


@pytest.mark.parametrize("operations", [
    {}, [], {"filter": "movie=https://example.com/a.mp4"}, {"brightness": "0.1"},
    {"brightness": True}, {"brightness": -1.01}, {"brightness": 1.01},
    {"contrast": -0.01}, {"contrast": 3.01}, {"saturation": -0.01}, {"saturation": 3.01},
    {"gamma": 0}, {"gamma": 10.01}, {"gamma": float("nan")}, {"gamma": float("inf")},
    {"gamma": 10**1000}, {"reverse": "true"}, {"extract_audio": 1},
    {"denoise_audio": None}, {"normalize_audio": False},
    {"extract_audio": True, "brightness": 0.1}, {"extract_audio": True, "reverse": True},
])
def test_invalid_effects_fail_before_any_write(operations, stub_source, tmp_path):
    output = tmp_path / "new"
    with pytest.raises(ValueError):
        processing.process_media(stub_source["path"], str(output), operations, False)
    assert not output.exists()


@pytest.mark.parametrize("duration", [None, 0, 600.01, 10000])
def test_reverse_rejects_unknown_or_long_input(duration, stub_source, tmp_path):
    stub_source["duration"] = duration
    with pytest.raises(ValueError, match="at most 600"):
        processing.process_media(stub_source["path"], str(tmp_path / "new"), {"reverse": True}, False)
    assert not (tmp_path / "new").exists()


def test_reverse_accepts_cap_and_numeric_range_endpoints(stub_source, tmp_path):
    stub_source["duration"] = 600
    result = processing.process_media(stub_source["path"], str(tmp_path / "new"),
        {"reverse": True, "brightness": -1, "contrast": 0, "saturation": 3, "gamma": 0.1})
    assert result["status"] == "validated"
    assert result["processing"]["timeout_seconds"] == 3600


@pytest.mark.parametrize("kind,audio,ops", [
    ("audio", True, {"brightness": 0}), ("audio", True, {"reverse": True}),
    ("image", False, {"normalize_audio": True}), ("video", False, {"extract_audio": True}),
    ("video", False, {"denoise_audio": True}),
])
def test_stream_mismatches_are_explicit(kind, audio, ops, stub_source, tmp_path):
    stub_source.update(kind=kind, has_audio=audio)
    with pytest.raises(ValueError):
        processing.process_media(stub_source["path"], str(tmp_path / "new"), ops, False)
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("time", [-1, 10, 11, float("nan"), float("inf"), True, "1"])
def test_invalid_frame_time_does_not_write(time, stub_source, tmp_path):
    with pytest.raises(ValueError):
        processing.extract_frame(stub_source["path"], time, str(tmp_path / "new"), False)
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("value", ["relative", "https://example.com/output", "file:///tmp/output", "", "\0"])
def test_output_requires_absolute_local_directory(value, stub_source):
    with pytest.raises(ValueError, match="absolute"):
        processing.process_media(stub_source["path"], value, {"reverse": True})


def test_output_symlink_and_existing_file_parent_rejected(stub_source, tmp_path):
    original = tmp_path / "keep.txt"
    original.write_text("keep")
    linked = tmp_path / "link"
    linked.symlink_to(tmp_path, target_is_directory=True)
    for output in (original, original / "child", linked):
        with pytest.raises(ValueError):
            processing.process_media(stub_source["path"], str(output), {"reverse": True}, False)
    assert original.read_text() == "keep"


def test_real_remote_and_playlist_inputs_are_rejected(tmp_path):
    playlist = tmp_path / "list.m3u8"
    playlist.write_text("#EXTM3U\nhttps://example.com/video.ts")
    for source in ("https://example.com/video.mp4", "file:///tmp/a.mp4", str(playlist)):
        with pytest.raises(ValueError):
            processing.process_media(source, str(tmp_path / "new"), {"reverse": True}, False)
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("operation", ["process", "frame"])
def test_dryrun_must_be_boolean(operation, stub_source, tmp_path):
    with pytest.raises(ValueError, match="dry_run"):
        if operation == "process":
            processing.process_media(stub_source["path"], str(tmp_path), {"reverse": True}, "false")
        else:
            processing.extract_frame(stub_source["path"], 1, str(tmp_path), "false")


@pytest.mark.parametrize("failure", ["exit", "timeout", "start", "empty", "probe", "commit"])
def test_failures_clean_staging_and_preserve_existing_files(failure, stub_source, tmp_path, monkeypatch):
    output = tmp_path / "out"
    output.mkdir()
    keep = output / "keep.mp4"
    keep.write_bytes(b"existing")
    def fake_run(command, **kwargs):
        assert command[command.index("-protocol_whitelist") + 1] == "file,pipe"
        assert "-nostdin" in command and "-n" in command
        assert kwargs["shell"] is False and kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] >= 120
        Path(command[-1]).write_bytes(b"partial")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if failure == "start":
            raise PermissionError(13, "Permission denied")
        if failure == "empty":
            Path(command[-1]).unlink()
        return subprocess.CompletedProcess(command, 1 if failure == "exit" else 0, "", "synthetic processing error")
    monkeypatch.setattr(processing.subprocess, "run", fake_run)
    if failure == "probe":
        def bad_probe(path):
            if path != stub_source["path"]:
                raise ValueError("Output media is unreadable")
            return stub_source.copy()
        monkeypatch.setattr(processing, "probe_media", bad_probe)
    if failure == "commit":
        original_link = processing.os.link
        def fail_record_link(source, target):
            if str(target).endswith(".json"):
                raise OSError("synthetic commit failure")
            return original_link(source, target)
        monkeypatch.setattr(processing.os, "link", fail_record_link)
    with pytest.raises((ValueError, OSError)):
        processing.process_media(stub_source["path"], str(output), {"reverse": True}, False)
    assert list(output.iterdir()) == [keep]
    assert keep.read_bytes() == b"existing"


def test_uuid_collision_cannot_overwrite_output_or_record(stub_source, tmp_path, monkeypatch):
    identifier = uuid.UUID(int=1)
    monkeypatch.setattr(processing.uuid, "uuid4", lambda: identifier)
    for suffix in (".mp4", ".processing.json"):
        occupied = tmp_path / f"processed_{identifier.hex}{suffix}"
        occupied.write_bytes(b"keep")
        with pytest.raises(ValueError, match="never replaced"):
            processing.process_media(stub_source["path"], str(tmp_path), {"reverse": True}, False)
        assert occupied.read_bytes() == b"keep"
        occupied.unlink()


def test_racing_record_file_survives_partial_commit(stub_source, tmp_path, monkeypatch):
    real_link = processing.os.link
    def competing_writer(source, target):
        if str(target).endswith(".json"):
            Path(target).write_bytes(b"other writer")
        return real_link(source, target)
    monkeypatch.setattr(processing.os, "link", competing_writer)
    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"synthetic output")
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(processing.subprocess, "run", fake_run)
    with pytest.raises(FileExistsError):
        processing.process_media(stub_source["path"], str(tmp_path), {"reverse": True}, False)
    files = list(tmp_path.iterdir())
    assert len(files) == 1 and files[0].suffix == ".json"
    assert files[0].read_bytes() == b"other writer"
