"""Transport views must be small by default and lossless when full is explicit."""
from copy import deepcopy
import json

import pytest

from jianying_local_mcp.responses import compact_result, project_view


def plan_with_clips(count=500):
    return {
        "name": "响应体积测试", "width": 1920, "height": 1080, "fps": 25,
        "custom_project_field": {"keep": "完整工程字段"},
        "clips": [{
            "id": f"clip-{index:04d}", "kind": "text", "track": "字幕" if index % 2 == 0 else "题字",
            "start": index * 2, "duration": 2, "text": f"第{index}段台词，唱念做打皆是功夫。",
            "font_size": 48, "color": "#FFFFFF", "x": 0, "y": -0.75,
            "text_style": {"stroke_color": "#000000", "stroke_width": 1},
            "keyframes": {prop: [{"time": step / 10, "value": step / 20} for step in range(21)]
                          for prop in ("x", "y", "opacity")},
        } for index in range(count)],
    }


def byte_count(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def test_write_metadata_survives_without_copying_full_plan():
    result = {"status": "created", "dry_run": False, "summary": {"name": "示例", "clip_count": 500},
              "project_dir": "/example/示例", "native_app_verified": False,
              "source_project_unchanged": "源稿", "validation": {"warnings": ["review"]},
              "plan": plan_with_clips()}
    before = deepcopy(result)
    compact = compact_result(result)
    assert "plan" not in compact and compact["plan_omitted"] is True
    for key, value in result.items():
        if key != "plan":
            assert compact[key] == value
    compact["validation"]["warnings"].clear()
    assert result == before
    full = compact_result(result, include_plan=True)
    assert full == result and full is not result
    full["plan"]["clips"].clear()
    assert result == before


def test_dry_run_hint_does_not_claim_preview_is_saved():
    result = compact_result({"status": "validated", "dry_run": True, "plan": plan_with_clips(1)})
    assert "not saved" in result["read_hint"]
    assert "include_plan=true" in result["read_hint"]
    assert "read_managed_project" not in result["read_hint"]


def test_result_without_plan_is_preserved():
    value = {"status": "published", "summary": {"clip_count": 1}}
    assert compact_result(value) == value
    assert compact_result(value) is not value


@pytest.mark.parametrize("value", [None, [], "invalid"])
def test_invalid_result(value):
    with pytest.raises(ValueError, match="result"):
        compact_result(value)


@pytest.mark.parametrize("value", [None, 1, 0, "false"])
def test_include_plan_requires_boolean(value):
    with pytest.raises(ValueError, match="include_plan"):
        compact_result({}, value)


def test_default_view_exposes_no_clips_or_plan():
    plan = plan_with_clips()
    result = project_view(plan)
    assert result["view"] == "summary"
    assert result["summary"]["clip_count"] == 500
    assert result["summary"]["duration"] == 1000
    assert "clips" not in result and "plan" not in result


def test_exact_track_filter_pagination_has_no_gaps_or_duplicate_ids():
    plan = plan_with_clips()
    first = project_view(plan, "clips", limit=200, track="字幕")
    second = project_view(plan, "clips", offset=first["next_offset"], limit=200, track="字幕")
    assert (first["total"], first["returned"], first["next_offset"]) == (250, 200, 200)
    assert (second["returned"], second["next_offset"]) == (50, None)
    assert [clip["id"] for clip in first["clips"] + second["clips"]] == [
        clip["id"] for clip in plan["clips"] if clip["track"] == "字幕"]
    assert "keyframes" not in first["clips"][0]
    assert "text_style" not in first["clips"][0]
    assert first["clips"][0]["text"] == plan["clips"][0]["text"]
    assert project_view(plan, "clips", track="字幕 ")["total"] == 0


@pytest.mark.parametrize("offset", [500, 501, 10000])
def test_end_and_out_of_range_offsets_are_empty(offset):
    result = project_view(plan_with_clips(), "clips", offset=offset)
    assert result["returned"] == 0 and result["clips"] == [] and result["next_offset"] is None


def test_full_view_is_lossless_even_for_long_strings_and_unknown_fields():
    plan = plan_with_clips(2)
    plan["clips"][0]["text"] = "全文不可静默截断🙂" * 10000
    plan["clips"][1]["path"] = "/example/原始视频.mp4"
    full = project_view(plan, "full")
    assert full == plan
    assert byte_count(full) == byte_count(plan)
    full["custom_project_field"]["keep"] = "changed"
    full["clips"][0]["keyframes"]["x"].clear()
    assert plan["custom_project_field"]["keep"] == "完整工程字段"
    assert len(plan["clips"][0]["keyframes"]["x"]) == 21


@pytest.mark.parametrize("kwargs", [
    {"view": "bogus"}, {"view": None}, {"view": []},
    {"offset": -1}, {"offset": 1.0}, {"offset": True},
    {"limit": 0}, {"limit": 201}, {"limit": 1.0}, {"limit": False},
    {"track": ""}, {"track": " "}, {"track": 1},
])
def test_invalid_view_arguments_are_rejected(kwargs):
    with pytest.raises(ValueError):
        project_view(plan_with_clips(1), **{"view": "clips", **kwargs})


@pytest.mark.parametrize("view", ["summary", "full"])
@pytest.mark.parametrize("kwargs", [{"offset": 1}, {"limit": 200}, {"track": "字幕"}])
def test_filter_or_paging_cannot_implicitly_modify_summary_or_full(view, kwargs):
    with pytest.raises(ValueError, match="only to the clips"):
        project_view(plan_with_clips(1), view, **kwargs)


@pytest.mark.parametrize("plan", [None, [], {}, {"clips": {}}])
def test_invalid_plan_is_rejected(plan):
    with pytest.raises(ValueError, match="plan"):
        project_view(plan)


def test_500_clip_response_byte_budget_and_no_side_effects():
    plan = plan_with_clips()
    before = deepcopy(plan)
    original = {"status": "created", "dry_run": False, "summary": {"clip_count": 500},
                "project_dir": "/example/响应体积测试", "plan": plan}
    full_bytes = byte_count(original)
    assert byte_count(compact_result(original)) < 1024
    assert byte_count(compact_result(original)) < full_bytes / 100
    assert byte_count(project_view(plan)) < 1024
    assert byte_count(project_view(plan, "clips")) < byte_count(plan) / 20
    assert plan == before
