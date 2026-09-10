"""Workflow checks use generated media and isolated temporary project folders."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import wave
import zlib

import pytest

from jianying_local_mcp.core import MANIFEST, ProjectStore, normalize_plan
from jianying_local_mcp.media import ffmpeg_path, local_media_path, probe_media


@pytest.fixture
def wav_file(tmp_path):
    path = tmp_path / "合成测试音频.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 8000 * 12)
    return path


@pytest.fixture
def audio_plan(wav_file):
    return {
        "name": "音频工程",
        "clips": [{"id": "narration", "kind": "audio", "track": "旁白", "path": str(wav_file),
                   "start": 2, "duration": 4, "source_start": 1, "speed": 2, "volume": 0.7}],
    }


def text_plan(name="字幕工程"):
    return {"name": name, "clips": [{"id": "title", "kind": "text", "track": "字幕",
            "start": 0, "duration": 2, "text": "你好，世界"}]}


def files_digest(directory):
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*") if path.is_file()
    }


def test_real_probe_reads_generated_local_audio(wav_file):
    metadata = probe_media(str(wav_file))
    assert metadata["path"] == str(wav_file.resolve())
    assert metadata["kind"] == "audio"
    assert metadata["has_audio"] is True
    assert metadata["duration"] == pytest.approx(12, abs=0.01)
    assert metadata["duration_precision"] == 1 / 8000
    assert metadata["bytes"] == wav_file.stat().st_size


@pytest.mark.parametrize("width,height", [(1, 1080), (3, 1080), (1920, 3), (1920, 1080)])
def test_real_probe_preserves_thin_png_dimensions(tmp_path, width, height):
    """Thin native line assets must retain exact dimensions through real probing."""
    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    path = tmp_path / f"gold-line-{width}x{height}.png"
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = (b"\0" + bytes((225, 186, 121)) * width) * height
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))

    metadata = probe_media(str(path))
    assert metadata["kind"] == "image"
    assert metadata["codec"] == "png"
    assert (metadata["width"], metadata["height"]) == (width, height)


def test_dry_run_validates_media_without_creating_workspace_or_mutating_inputs(tmp_path, audio_plan):
    workspace = tmp_path / "not-created-yet"
    before = deepcopy(audio_plan)
    before_files = files_digest(tmp_path)
    result = ProjectStore(workspace).create(audio_plan)
    assert result["status"] == "validated"
    assert result["dry_run"] is True
    assert result["summary"]["duration"] == 6
    assert result["summary"]["tracks"] == ["旁白"]
    assert not workspace.exists()
    assert files_digest(tmp_path) == before_files
    assert audio_plan == before


def test_real_create_packages_media_once_and_writes_self_contained_project(tmp_path, audio_plan, wav_file):
    audio_plan["clips"][0]["display_name"] = "01_旁白_开始"
    audio_plan["clips"].append({**audio_plan["clips"][0], "id": "repeat", "start": 6,
                                "display_name": "02_旁白_传承"})
    original = wav_file.read_bytes()
    result = ProjectStore(tmp_path / "projects").create(audio_plan, dry_run=False)
    target = Path(result["project_dir"])
    assert result["status"] == "created"
    assert result["native_app_verified"] is False
    assert {p.name for p in target.iterdir()} >= {MANIFEST, "draft_info.json", "draft_meta_info.json", "Resources"}
    resources = list((target / "Resources").iterdir())
    assert len(resources) == 1
    assert resources[0].read_bytes() == original
    manifest = json.loads((target / MANIFEST).read_text())
    assert manifest["format"] == "jianying-local-mcp"
    assert all(Path(clip["path"]) == resources[0] for clip in manifest["plan"]["clips"])
    assert [c["display_name"] for c in manifest["plan"]["clips"]] == ["01_旁白_开始", "02_旁白_传承"]
    draft = json.loads((target / "draft_info.json").read_text())
    assert {m["name"] for m in draft["materials"]["audios"]} == {"01_旁白_开始", "02_旁白_传承"}
    assert {m["path"] for m in draft["materials"]["audios"]} == {str(resources[0])}
    assert wav_file.read_bytes() == original
    assert not list(target.parent.glob(".staging-*"))


def test_revision_preserves_entire_original_project_and_repackages_media(tmp_path, audio_plan):
    store = ProjectStore(tmp_path / "projects")
    first = store.create(audio_plan, dry_run=False)
    first_dir = Path(first["project_dir"])
    baseline = files_digest(first_dir)
    revised = store.edit("音频工程", "音频工程_修订", [
        {"op": "update", "id": "narration", "changes": {"volume": 0.3, "start": 0,
                                                        "display_name": "01_旁白_开场"}},
    ], dry_run=False)
    assert revised["source_project_unchanged"] == "音频工程"
    assert files_digest(first_dir) == baseline
    assert store.load_managed("音频工程")["clips"][0]["volume"] == 0.7
    new_plan = store.load_managed("音频工程_修订")
    assert new_plan["clips"][0]["volume"] == 0.3
    assert new_plan["clips"][0]["start"] == 0
    assert new_plan["clips"][0]["display_name"] == "01_旁白_开场"
    assert Path(new_plan["clips"][0]["path"]).parent == Path(revised["project_dir"]) / "Resources"
    assert {row["name"] for row in store.list_projects()} == {"音频工程", "音频工程_修订"}


def test_split_at_double_speed_advances_source_by_twice_elapsed_timeline(tmp_path, audio_plan):
    store = ProjectStore(tmp_path / "projects")
    store.create(audio_plan, dry_run=False)
    before = files_digest(store.workspace)
    result = store.edit("音频工程", "拆分预览", [{"op": "split", "id": "narration", "at": 3.5}])
    left, right = result["plan"]["clips"]
    assert (left["start"], left["duration"], left["source_start"], left["speed"]) == (2, 1.5, 1, 2)
    assert (right["start"], right["duration"], right["source_start"], right["speed"]) == (3.5, 2.5, 4, 2)
    assert left["id"] != right["id"]
    assert right["source_start"] + right["duration"] * right["speed"] == 9
    assert files_digest(store.workspace) == before
    assert not (store.workspace / "拆分预览").exists()


@pytest.mark.parametrize("change", [{"duration": 6}, {"source_start": 13}, {"source_start": -1}])
def test_invalid_source_range_is_rejected_before_writing(tmp_path, audio_plan, change):
    audio_plan["clips"][0].update(change)
    store = ProjectStore(tmp_path / "projects")
    with pytest.raises(ValueError):
        store.create(audio_plan, dry_run=False)
    assert not store.workspace.exists()


@pytest.mark.parametrize("field", ["start", "duration", "source_start", "speed", "volume", "x", "y", "font_size"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_clip_values_are_rejected(field, invalid):
    plan = text_plan()
    plan["clips"][0][field] = invalid
    with pytest.raises(ValueError):
        normalize_plan(plan)


@pytest.mark.parametrize("field", ["width", "height", "fps"])
def test_nonfinite_canvas_values_are_rejected(field):
    plan = text_plan()
    plan[field] = float("nan")
    with pytest.raises(ValueError):
        normalize_plan(plan)


def test_same_track_overlap_rejected_but_separate_track_overlay_allowed():
    plan = text_plan()
    plan["clips"].append({"id": "second", "kind": "text", "track": "字幕", "start": 1, "duration": 2, "text": "重叠"})
    with pytest.raises(ValueError, match="overlapping"):
        normalize_plan(plan)
    plan["clips"][1]["track"] = "另一个字幕轨"
    assert len(normalize_plan(plan)["clips"]) == 2


@pytest.mark.parametrize("kind", ["video", "image", "audio"])
def test_normalize_keeps_media_display_name(kind):
    def probe(path):
        return {"path": path, "kind": kind, "duration": 2,
                "width": 1920, "height": 1080, "has_audio": kind != "image"}

    plan = {"name": "命名片段", "clips": [{"id": "first", "kind": kind,
            "path": "/example/source.mov", "duration": 1, "display_name": "01_走近_舞台"}]}
    assert normalize_plan(plan, probe)["clips"][0]["display_name"] == "01_走近_舞台"


@pytest.mark.parametrize("invalid", [None, 1, "", "  ", "x" * 121, "a\nb", "a\tb",
                                     "a\x7fb", "a\u0085b", "a\u202eb", "a\ud800b"])
def test_invalid_media_display_names_are_rejected_before_probing(invalid):
    plan = {"name": "命名校验", "clips": [{"kind": "video", "path": "/example/source.mov",
            "duration": 1, "display_name": invalid}]}
    with pytest.raises(ValueError, match="display_name"):
        normalize_plan(plan, lambda path: pytest.fail("invalid name reached media probe"))


def test_text_uses_its_content_instead_of_a_media_display_name():
    plan = text_plan()
    plan["clips"][0]["display_name"] = "名字"
    with pytest.raises(ValueError, match="only supported"):
        normalize_plan(plan)


@pytest.mark.parametrize("name", ["../escape", "a/../../escape", "/absolute", "a\\escape", "..", ".hidden", " name", "a:b"])
def test_project_path_traversal_and_ambiguous_names_rejected(tmp_path, name):
    store = ProjectStore(tmp_path / "projects")
    with pytest.raises(ValueError):
        store.create(text_plan(name), dry_run=False)
    assert not store.workspace.exists()


@pytest.mark.parametrize("dangling", [False, True])
def test_output_project_symlink_is_rejected_and_destination_untouched(tmp_path, dangling):
    workspace = tmp_path / "projects"
    workspace.mkdir()
    external = tmp_path / "external"
    if not dangling:
        external.mkdir()
        (external / "keep.txt").write_text("keep")
    (workspace / "linked").symlink_to(external, target_is_directory=True)
    before = files_digest(tmp_path)
    store = ProjectStore(workspace)
    with pytest.raises(ValueError):
        store.create(text_plan("linked"), dry_run=False)
    with pytest.raises(ValueError):
        store.load_managed("linked")
    assert (workspace / "linked").is_symlink()
    assert files_digest(tmp_path) == before
    assert external.exists() is (not dangling)


def test_existing_project_cannot_be_overwritten(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    result = store.create(text_plan(), dry_run=False)
    before = files_digest(Path(result["project_dir"]))
    with pytest.raises(ValueError, match="already exists"):
        store.create(text_plan(), dry_run=False)
    assert files_digest(Path(result["project_dir"])) == before


@pytest.mark.parametrize("path", ["relative.mp4", "https://example.com/video.mp4", "file:///tmp/a.mp4", "\0"])
def test_media_paths_require_absolute_local_files(path):
    with pytest.raises(ValueError):
        local_media_path(path)


def test_media_playlist_rejected(tmp_path):
    playlist = tmp_path / "playlist.m3u8"
    playlist.write_text("#EXTM3U\nhttps://example.com/video.ts")
    with pytest.raises(ValueError, match="Unsupported"):
        local_media_path(str(playlist))


def test_valid_fractional_full_media_duration_can_be_written_after_dry_run(tmp_path):
    path = tmp_path / "fractional.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * 9872)
    exact_duration = 9872 / 8000
    assert probe_media(str(path))["duration"] == exact_duration
    plan = {"name": "小数时长", "clips": [{"kind": "audio", "path": str(path),
            "start": 0, "duration": exact_duration}]}
    store = ProjectStore(tmp_path / "projects")
    preview = store.create(plan)
    created = store.create(plan, dry_run=False)
    assert preview["status"] == "validated"
    assert created["status"] == "created"
    assert created["summary"]["duration"] == preview["summary"]["duration"]


def test_mp3_with_attached_album_cover_is_accepted_as_audio(tmp_path):
    path = tmp_path / "music-with-cover.mp3"
    subprocess.run([
        ffmpeg_path(), "-nostdin", "-v", "error",
        "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
        "-f", "lavfi", "-i", "color=c=red:s=32x32", "-t", "1",
        "-map", "0:a", "-map", "1:v", "-c:a", "libmp3lame",
        "-c:v", "mjpeg", "-disposition:v", "attached_pic", str(path),
    ], capture_output=True, check=True, timeout=20)
    metadata = probe_media(str(path))
    assert metadata["kind"] == "audio"
    assert metadata["has_audio"] is True
    assert metadata["duration_precision"] == 0.01
    normalized = normalize_plan({"name": "封面音乐", "clips": [{"kind": "audio", "path": str(path),
                                "start": 0, "duration": 0.5}]})
    assert normalized["clips"][0]["kind"] == "audio"


def test_listing_reports_corrupt_manifest_without_hiding_valid_projects(tmp_path):
    store = ProjectStore(tmp_path / "projects")
    store.create(text_plan(), dry_run=False)
    broken = store.workspace / "broken"
    broken.mkdir()
    (broken / MANIFEST).write_text(json.dumps({
        "format": "jianying-local-mcp", "format_version": 1, "plan": None,
    }))
    listing = {item["name"]: item for item in store.list_projects()}
    assert listing["broken"]["status"] == "invalid_manifest"
    assert listing["字幕工程"]["clip_count"] == 1


@pytest.mark.parametrize("long_first", [True, False])
def test_repeated_media_accepts_shared_duration_tolerance_in_either_order(tmp_path, wav_file, long_first):
    durations = [12.004, 1] if long_first else [1, 12.004]
    clips = []
    start = 0
    for index, duration in enumerate(durations):
        clips.append({"kind": "audio", "id": f"audio-{index}", "path": str(wav_file),
                      "track": "audio", "start": start, "duration": duration})
        start += duration
    store = ProjectStore(tmp_path / "projects")
    plan = {"name": "重复素材边界", "clips": clips}
    assert store.create(plan)["status"] == "validated"
    created = store.create(plan, dry_run=False)
    draft = json.loads((Path(created["project_dir"]) / "draft_info.json").read_text())
    material = draft["materials"]["audios"][0]
    for segment in draft["tracks"][0]["segments"]:
        source = segment["source_timerange"]
        assert source["start"] + source["duration"] <= material["duration"]


@pytest.mark.parametrize("dry_run", [True, False])
def test_source_overrun_outside_shared_precision_limit_is_rejected(tmp_path, wav_file, dry_run):
    store = ProjectStore(tmp_path / "projects")
    with pytest.raises(ValueError, match="source range"):
        store.create({"name": "越界", "clips": [{"kind": "audio", "path": str(wav_file),
                      "start": 0, "duration": 12.006}]}, dry_run=dry_run)
    assert not store.workspace.exists()


def test_dry_run_checks_native_schema_before_any_output_write(tmp_path):
    path = tmp_path / "bad-dimensions.mov"
    path.write_bytes(b"synthetic metadata test")

    def invalid_dimensions_probe(value):
        return {"path": value, "kind": "video", "duration": 2,
                "width": 0, "height": 0, "has_audio": False}

    store = ProjectStore(tmp_path / "projects", probe=invalid_dimensions_probe)
    with pytest.raises(ValueError, match="media_width"):
        store.create({"name": "无效尺寸", "clips": [{"kind": "video", "path": str(path),
                      "start": 0, "duration": 1}]})
    assert not store.workspace.exists()


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("ffmpeg", 30), PermissionError(13, "Permission denied")])
def test_ffmpeg_process_failures_are_clear_validation_errors(wav_file, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr("jianying_local_mcp.media.subprocess.run", fail)
    with pytest.raises(ValueError, match="timed out|Could not start"):
        probe_media(str(wav_file))
