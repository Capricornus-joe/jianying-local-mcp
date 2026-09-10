"""Timeline workflow tests use synthetic local files and deterministic probes."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from jianying_local_mcp.core import MANIFEST, ProjectStore
from jianying_local_mcp.subtitles import parse_srt
from jianying_local_mcp.workflow import (
    export_srt, montage_create, reorder_track, ripple_delete, style_subtitles,
)


@pytest.fixture
def media_store(tmp_path):
    def probe(path):
        path = Path(path).resolve(strict=True)
        metadata = json.loads(path.read_text())
        return {**metadata, "path": str(path)}

    def media(name, kind="video", duration=256):
        path = tmp_path / name
        path.write_text(json.dumps({"kind": kind, "duration": duration,
                        "width": 1920 if kind != "audio" else 0,
                        "height": 1080 if kind != "audio" else 0,
                        "has_audio": kind in {"video", "audio"}, "rotation": 0}))
        return str(path)

    return ProjectStore(tmp_path / "projects", probe=probe), media


def snapshot(folder):
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob("*") if path.is_file()}


def by_id(plan):
    return {clip["id"]: clip for clip in plan["clips"]}


def text(clip_id, start, duration, track="字幕", content="测试字幕"):
    return {"id": clip_id, "kind": "text", "track": track, "start": start,
            "duration": duration, "text": content}


def assert_tracks_do_not_overlap(plan):
    for track in {clip["track"] for clip in plan["clips"]}:
        previous_end = -1
        for clip in sorted((c for c in plan["clips"] if c["track"] == track), key=lambda c: c["start"]):
            start = round(clip["start"] * 1_000_000)
            assert start >= previous_end
            previous_end = start + round(clip["duration"] * 1_000_000)


def test_reorder_closes_gaps_in_requested_order_and_preserves_other_tracks(media_store):
    store, media = media_store
    video = media("source.mp4")
    original = store.create({"name": "原工程", "clips": [
        {"id": "a", "kind": "video", "path": video, "track": "主画面", "start": 2, "duration": 1, "source_start": 5},
        text("subtitle", 4, 2),
        {"id": "b", "kind": "video", "path": video, "track": "主画面", "start": 6, "duration": 2, "source_start": 10, "speed": 2},
        {"id": "c", "kind": "video", "path": video, "track": "主画面", "start": 9, "duration": 0.5, "source_start": 20},
    ]}, dry_run=False)
    before = snapshot(store.workspace)
    result = reorder_track(store, "原工程", "重排预览", "主画面", ["c", "a", "b"], start=0.25)
    reordered = [clip for clip in result["plan"]["clips"] if clip["track"] == "主画面"]
    assert [clip["id"] for clip in reordered] == ["c", "a", "b"]
    assert [clip["start"] for clip in reordered] == [0.25, 0.75, 1.75]
    assert [clip["source_start"] for clip in reordered] == [20, 5, 10]
    assert [clip["speed"] for clip in reordered] == [1, 1, 2]
    assert by_id(result["plan"])["subtitle"] == by_id(original["plan"])["subtitle"]
    assert snapshot(store.workspace) == before
    assert result["source_project_unchanged"] == "原工程"
    assert_tracks_do_not_overlap(result["plan"])


@pytest.mark.parametrize("clip_ids", [["a"], ["a", "a"], ["a", "missing"], ["a", "subtitle"]])
def test_reorder_rejects_incomplete_duplicate_or_foreign_ids(media_store, clip_ids):
    store, _ = media_store
    store.create({"name": "原工程", "clips": [text("a", 0, 1), text("b", 1, 1), text("subtitle", 0, 2, track="其他轨")]}, dry_run=False)
    with pytest.raises(ValueError):
        reorder_track(store, "原工程", "不会生成", "字幕", clip_ids, dry_run=False)
    assert not (store.workspace / "不会生成").exists()


def test_ripple_crosses_video_audio_and_text_boundaries_and_preserves_source(media_store):
    store, media = media_store
    video = media("source.mp4")
    audio = media("audio.wav", "audio")
    original = store.create({"name": "原工程", "clips": [
        {"id": "before", "kind": "video", "path": video, "track": "画面", "start": 0, "duration": 2},
        {"id": "cross", "kind": "video", "path": video, "track": "画面", "start": 2, "duration": 6, "source_start": 1, "speed": 2},
        {"id": "after", "kind": "video", "path": video, "track": "画面", "start": 9, "duration": 1},
        {"id": "music", "kind": "audio", "path": audio, "track": "音乐", "start": 0, "duration": 12},
        text("before_text", 1, 1), text("cross_text", 3, 4), text("after_text", 10, 1),
        text("removed_text", 4.2, 0.4, track="标签"),
    ]}, dry_run=False)
    source_directory = Path(original["project_dir"])
    before = snapshot(source_directory)
    revised = ripple_delete(store, "原工程", "删除中段", 4, 6, dry_run=False)
    clips = revised["plan"]["clips"]
    ids = by_id(revised["plan"])
    assert "removed_text" not in ids
    assert (ids["cross"]["start"], ids["cross"]["duration"], ids["cross"]["source_start"]) == (2, 2, 1)
    right_video = next(clip for clip in clips if clip["track"] == "画面" and clip["start"] == 4)
    assert (right_video["duration"], right_video["source_start"], right_video["speed"]) == (2, 9, 2)
    assert ids["after"]["start"] == 7
    music = [clip for clip in clips if clip["track"] == "音乐"]
    assert [(clip["start"], clip["duration"], clip["source_start"]) for clip in music] == [(0, 4, 0), (4, 6, 6)]
    subtitles = [clip for clip in clips if clip["track"] == "字幕"]
    assert [(clip["start"], clip["duration"]) for clip in subtitles] == [(1, 1), (3, 1), (4, 1), (8, 1)]
    assert all(clip["source_start"] == 0 for clip in subtitles)
    assert revised["summary"]["duration"] == 10
    assert len({clip["id"] for clip in clips}) == len(clips)
    assert snapshot(source_directory) == before
    assert_tracks_do_not_overlap(revised["plan"])


@pytest.mark.parametrize("speed", [0.1, 0.5, 1, 1.25, 2, 16])
def test_ripple_preserves_media_sampling_positions_at_every_supported_speed(media_store, speed):
    store, media = media_store
    path = media("source.mp4")
    store.create({"name": "原工程", "clips": [{"id": "source", "kind": "video", "path": path,
                  "track": "画面", "start": 2, "duration": 8, "source_start": 3, "speed": speed}]}, dry_run=False)
    result = ripple_delete(store, "原工程", "预览", 4, 6)
    left, right = result["plan"]["clips"]
    assert (left["start"], left["duration"]) == (2, 2)
    assert (right["start"], right["duration"]) == (4, 4)
    for clip in (left, right):
        for fraction in (0.1, 0.5, 0.9):
            new_timeline = clip["start"] + clip["duration"] * fraction
            old_timeline = new_timeline if new_timeline < 4 else new_timeline + 2
            expected_source = 3 + (old_timeline - 2) * speed
            actual_source = clip["source_start"] + (new_timeline - clip["start"]) * clip["speed"]
            assert actual_source == pytest.approx(expected_source, abs=0.000001)
    assert right["source_start"] + right["duration"] * speed == pytest.approx(3 + 8 * speed)
    assert_tracks_do_not_overlap(result["plan"])


def test_ripple_in_a_gap_still_shifts_all_later_tracks(media_store):
    store, _ = media_store
    store.create({"name": "原工程", "clips": [text("left", 0, 2), text("right", 8, 2), text("other", 9, 1, track="其他")]}, dry_run=False)
    result = ripple_delete(store, "原工程", "删空白", 3, 5)
    assert {clip["id"]: clip["start"] for clip in result["plan"]["clips"]} == {"left": 0, "right": 6, "other": 7}


def test_ripple_can_remove_the_entire_timeline(media_store):
    store, _ = media_store
    store.create({"name": "原工程", "clips": [text("only", 0, 2)]}, dry_run=False)
    result = ripple_delete(store, "原工程", "空工程", 0, 2)
    assert result["plan"]["clips"] == []
    assert result["summary"]["duration"] == 0


def test_ripple_refuses_nonempty_submillisecond_remnants(media_store):
    store, _ = media_store
    store.create({"name": "原工程", "clips": [text("tiny-left", 3.9995, 3)]}, dry_run=False)
    before = snapshot(store.workspace)
    with pytest.raises(ValueError, match="shorter than 1 ms"):
        ripple_delete(store, "原工程", "不应生成", 4, 6, dry_run=False)
    assert snapshot(store.workspace) == before


@pytest.mark.parametrize("start,end", [(2, 2), (3, 2), (-1, 2), (0, 3), (float("nan"), 2), (0, float("inf"))])
def test_ripple_rejects_invalid_intervals(media_store, start, end):
    store, _ = media_store
    store.create({"name": "原工程", "clips": [text("only", 0, 2)]}, dry_run=False)
    with pytest.raises(ValueError):
        ripple_delete(store, "原工程", "无效", start, end)


@pytest.mark.parametrize("advanced_field,payload", [
    ("keyframes", [{"future_animation": True}]),
    ("animations", [{"future_animation": True}]),
    ("audio_fade", {"in": 0.2, "out": 0}),
    ("transition_out", {"duration": 0.2}),
])
@pytest.mark.parametrize("operation", ["ripple", "reorder"])
def test_workflows_refuse_unmapped_animation_changes(media_store, advanced_field, payload, operation):
    store, _ = media_store
    source = store.create({"name": "原工程", "clips": [text("animated", 0, 5)]}, dry_run=False)
    manifest_path = Path(source["project_dir"]) / MANIFEST
    manifest = json.loads(manifest_path.read_text())
    manifest["plan"]["clips"][0][advanced_field] = payload
    manifest_path.write_text(json.dumps(manifest))
    before = snapshot(store.workspace)
    with pytest.raises(ValueError, match="keyframes or animations"):
        if operation == "ripple":
            ripple_delete(store, "原工程", "不会生成", 1, 2, dry_run=False)
        else:
            reorder_track(store, "原工程", "不会生成", "字幕", ["animated"], start=1, dry_run=False)
    assert snapshot(store.workspace) == before


@pytest.mark.parametrize("operation", ["ripple", "reorder"])
def test_unchanged_transition_owner_cannot_silently_gain_a_new_neighbor(media_store, operation):
    store, _ = media_store
    source = store.create({"name": "原工程", "clips": [text("a", 0, 1), text("b", 1, 1), text("c", 2, 1)]}, dry_run=False)
    manifest_path = Path(source["project_dir"]) / MANIFEST
    manifest = json.loads(manifest_path.read_text())
    manifest["plan"]["clips"][0]["transition_out"] = {"duration": 0.2}
    manifest_path.write_text(json.dumps(manifest))
    before = snapshot(store.workspace)
    with pytest.raises(ValueError, match="neighboring clip"):
        if operation == "ripple":
            ripple_delete(store, "原工程", "不生成", 1, 2, dry_run=False)
        else:
            reorder_track(store, "原工程", "不生成", "字幕", ["a", "c", "b"], dry_run=False)
    assert snapshot(store.workspace) == before


def test_zero_audio_fades_do_not_block_simple_ripple(media_store):
    store, media = media_store
    path = media("audio.wav", "audio")
    store.create({"name": "原工程", "clips": [{"id": "audio", "kind": "audio", "path": path,
                  "track": "音乐", "start": 0, "duration": 5, "audio_fade": {"in": 0, "out": 0}}]}, dry_run=False)
    result = ripple_delete(store, "原工程", "修订", 1, 2)
    assert result["summary"]["duration"] == 4
    assert len(result["plan"]["clips"]) == 2


def test_batch_subtitle_style_applies_to_selection_and_preserves_text_times(media_store):
    store, _ = media_store
    original = store.create({"name": "原工程", "clips": [text("a", 0, 1), text("b", 1, 1), text("label", 0, 2, track="标签")]}, dry_run=False)
    before = snapshot(Path(original["project_dir"]))
    result = style_subtitles(store, "原工程", "统一字幕", {"font_size": 60, "color": "#ffcc00", "y": -0.6}, track="字幕", dry_run=False)
    for clip in result["plan"]["clips"]:
        if clip["track"] == "字幕":
            assert (clip["font_size"], clip["color"], clip["y"]) == (60, "#FFCC00", -0.6)
            original_clip = by_id(original["plan"])[clip["id"]]
            assert (clip["text"], clip["start"], clip["duration"]) == (original_clip["text"], original_clip["start"], original_clip["duration"])
        else:
            assert clip == by_id(original["plan"])["label"]
    assert snapshot(Path(original["project_dir"])) == before


@pytest.mark.parametrize("style,ids", [({"unknown": 1}, None), ({}, None), ({"font_size": float("nan")}, None),
                                      ({"color": "red"}, None), ({"x": 0}, ["missing"]), ({"x": 0}, [])])
def test_subtitle_style_rejects_invalid_updates_or_selections(media_store, style, ids):
    store, _ = media_store
    store.create({"name": "原工程", "clips": [text("a", 0, 1)]}, dry_run=False)
    with pytest.raises(ValueError):
        style_subtitles(store, "原工程", "无效", style, clip_ids=ids)


def test_srt_export_round_trips_literal_chinese_multiline_text_without_writes(media_store):
    store, _ = media_store
    store.create({"name": "原工程", "clips": [
        text("later", 2.125, 1.875, content="第二句"),
        text("first", 0.125, 1.5, content="第一行\n<b>中文原样</b>\t& 字幕"),
        text("overlay", 1, 1, track="标签", content="重叠文字"),
    ]}, dry_run=False)
    before = snapshot(store.workspace)
    exported = export_srt(store, "原工程")
    parsed = parse_srt(exported["content"])
    assert exported["cue_count"] == 3
    assert [clip["start"] for clip in parsed] == [0.125, 1, 2.125]
    assert parsed[0]["text"] == "第一行\n<b>中文原样</b>\t& 字幕"
    assert parsed[2]["duration"] == 1.875
    assert export_srt(store, "原工程", track="字幕")["cue_count"] == 2
    assert snapshot(store.workspace) == before


def test_srt_export_rounds_milliseconds_with_rollover(media_store):
    store, _ = media_store
    store.create({"name": "原工程", "clips": [text("rollover", 59.9995, 1)]}, dry_run=False)
    assert "00:01:00,000 --> 00:01:01,000" in export_srt(store, "原工程")["content"]


def test_srt_export_refuses_blank_lines_instead_of_breaking_cue_boundaries(media_store):
    store, _ = media_store
    store.create({"name": "原工程", "clips": [text("ambiguous", 0, 2, content="第一段\n\n第二段")]}, dry_run=False)
    with pytest.raises(ValueError, match="blank lines"):
        export_srt(store, "原工程")


@pytest.mark.parametrize("fixed,expected", [(None, [5.123456, 3, 1.25, 5.123456]), (2.5, [2.5, 2.5, 1.25, 2.5])])
def test_montage_keeps_path_order_and_uses_full_or_fixed_durations(media_store, fixed, expected):
    store, media = media_store
    first = media("video1.mp4", duration=5.123456)
    picture = media("picture.png", "image", duration=None)
    short = media("video2.mp4", duration=1.25)
    paths = [first, picture, short, first]
    result = montage_create(store, "自动拼接", paths, clip_duration=fixed)
    clips = result["plan"]["clips"]
    assert [clip["path"] for clip in clips] == paths
    assert [clip["duration"] for clip in clips] == expected
    assert [clip["kind"] for clip in clips] == ["video", "image", "video", "video"]
    assert all(clip["source_start"] == 0 and clip["speed"] == 1 for clip in clips)
    assert result["summary"]["duration"] == pytest.approx(sum(expected))
    assert not store.workspace.exists()
    assert_tracks_do_not_overlap(result["plan"])
    created = montage_create(store, "实际拼接", paths, clip_duration=fixed, dry_run=False)
    assert created["status"] == "created"
    assert len(list((Path(created["project_dir"]) / "Resources").iterdir())) == 3


def test_montage_rejects_audio_without_silently_skipping_it(media_store):
    store, media = media_store
    video = media("video.mp4", duration=2)
    audio = media("music.wav", "audio", duration=2)
    with pytest.raises(ValueError, match="audio-only"):
        montage_create(store, "无效", [video, audio], dry_run=False)
    assert not store.workspace.exists()


@pytest.mark.parametrize("paths,duration", [([], None), ([None], None), (["unused.mp4"], float("nan")), (["unused.mp4"], 0)])
def test_montage_rejects_invalid_inputs_before_probe(media_store, paths, duration):
    store, _ = media_store
    with pytest.raises(ValueError):
        montage_create(store, "无效", paths, clip_duration=duration)
    assert not store.workspace.exists()
