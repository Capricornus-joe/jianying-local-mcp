"""Validate discovery against synthetic caches without touching user data."""

import json
from pathlib import Path

import pytest

from jianying_local_mcp.resources import list_resources, resolve_resource


VIDEO_FADE = "6798320778182922760"
TEXT_FADE = "6724916044072227332"
DISSOLVE = "6724845717472416269"


def animation(root, resource_id=VIDEO_FADE, version="a" * 32):
    bundle = root / resource_id / version
    bundle.mkdir(parents=True)
    (bundle / "config.json").write_text(json.dumps({"effect": {"Link": [{"type": "InfoSticker"}]}, "version": "3.1.1"}))
    (bundle / "content.json").write_text(json.dumps({"filemap": {"prefab": "anim.prefab"}}))
    (bundle / "anim.prefab").write_text("synthetic prefab")
    return bundle


def transition(root, resource_id=DISSOLVE, version="b" * 32):
    bundle = root / resource_id / version
    payload = bundle / "AmazingAuto_out"
    payload.mkdir(parents=True)
    (bundle / "config.json").write_text(json.dumps({"effect": {"Link": [{"type": "AmazingFeature", "path": "AmazingAuto_out/"}]}, "version": "13.3.0"}))
    (bundle / "extra.json").write_text(json.dumps({"transition": {"defaultDura": 0.5, "isOverlap": True}}))
    (payload / "content.json").write_text(json.dumps({"ae_tool": "AmazingEditor", "version": "1.0"}))
    (payload / "main.scene").write_text("synthetic scene")
    return bundle


def test_missing_cache_lists_only_audited_metadata_and_writes_nothing(tmp_path):
    root = tmp_path / "effect"
    result = list_resources(cache_root=root)
    assert result["count"] == 7
    assert result["cached_count"] == 0
    assert result["coverage"] == "small_reviewed_catalog_only"
    assert not root.exists()
    for item in result["resources"]:
        assert item["path"] is None
        assert item["cached"] is False
        assert item["native_app_verified"] is False
        assert item["entitlement_verified"] is False
        assert item["free_status"] == "free_in_catalog"
        assert item["is_vip"] is False
        assert item["source_license"] == "Apache-2.0"
        assert item["catalog_source"].startswith("https://github.com/GuanYixuan/pyJianYingDraft/")


def test_resolves_video_and_text_fades_with_distinct_original_ids(tmp_path):
    video = animation(tmp_path, VIDEO_FADE)
    text = animation(tmp_path, TEXT_FADE)
    selected_video = resolve_resource("video_animation", "渐显", tmp_path)
    selected_text = resolve_resource("text_animation", "渐显", tmp_path)
    assert (selected_video["effect_id"], selected_video["resource_id"], selected_video["path"]) == ("624705", VIDEO_FADE, str(video))
    assert (selected_text["effect_id"], selected_text["resource_id"], selected_text["path"]) == ("1644304", TEXT_FADE, str(text))
    assert selected_video["animation_type"] == "in"
    assert selected_video["cached"] is True
    assert selected_video["cache_status"] == "catalog_id_and_package_structure_match"
    assert selected_video["native_app_verified"] is False
    assert "category_id" not in selected_video
    assert list_resources("animation", "渐显", tmp_path)["count"] == 2
    with pytest.raises(ValueError, match="exactly one"):
        resolve_resource("animation", "渐显", tmp_path)


def test_transition_has_evidenced_overlap_and_validated_scene(tmp_path):
    bundle = transition(tmp_path)
    result = resolve_resource("transition", "叠化", tmp_path)
    assert result["resource_id"] == DISSOLVE
    assert result["effect_id"] == "322577"
    assert result["path"] == str(bundle)
    assert result["default_duration"] == 0.5
    assert result["is_overlap"] is True
    assert result["cache_candidates"][0]["evidence"]["cached_transition_defaults"] == {"defaultDura": 0.5, "isOverlap": True}
    (bundle / "AmazingAuto_out" / "main.scene").unlink()
    assert list_resources("transition", "叠化", tmp_path)["resources"][0]["cached"] is False


def test_query_can_use_ids_or_aliases_without_inventing_official_names(tmp_path):
    animation(tmp_path)
    assert resolve_resource("video_animation", "624705", tmp_path)["name"] == "渐显"
    assert resolve_resource("video_animation", "fade in", tmp_path)["name"] == "渐显"
    result = list_resources("transition", "推移", tmp_path)
    assert {item["name"] for item in result["resources"]} == {"左移", "右移"}
    assert all(item["cached"] is False for item in result["resources"])


def test_arbitrary_directories_and_spoofed_config_names_do_not_become_verified(tmp_path):
    animation(tmp_path, "1234567890")
    known = animation(tmp_path, VIDEO_FADE)
    (known / "config.json").write_text(json.dumps({"name": "欺骗名称",
                                     "effect": {"Link": [{"type": "InfoSticker"}]}}))
    result = list_resources(cache_root=tmp_path)
    assert len(result["resources"]) == 7
    assert all(item["resource_id"] != "1234567890" for item in result["resources"])
    assert resolve_resource("video_animation", "渐显", tmp_path)["name"] == "渐显"
    assert list_resources(query="欺骗名称", cache_root=tmp_path)["count"] == 0
    assert list_resources(query="1234567890", cache_root=tmp_path)["count"] == 0


def test_explicit_cached_id_conflict_is_not_trusted_from_directory_name(tmp_path):
    bundle = animation(tmp_path)
    (bundle / "config.json").write_text(json.dumps({"resource_id": "999",
                                      "effect": {"Link": [{"type": "InfoSticker"}]}}))
    item = list_resources("video_animation", "渐显", tmp_path)["resources"][0]
    assert item["cached"] is False
    assert "conflicts" in item["rejected_candidates"][0]["reason"]


@pytest.mark.parametrize("missing", ["config.json", "content.json", "anim.prefab"])
def test_incomplete_animation_is_not_marked_cached(tmp_path, missing):
    bundle = animation(tmp_path)
    (bundle / missing).unlink()
    item = list_resources("video_animation", "渐显", tmp_path)["resources"][0]
    assert item["cached"] is False
    assert item["path"] is None
    assert item["rejected_candidates"]
    with pytest.raises(ValueError, match="no unique validated local cache"):
        resolve_resource("video_animation", "渐显", tmp_path)


def test_multiple_valid_versions_require_explicit_resolution_instead_of_guessing(tmp_path):
    first = animation(tmp_path, version="a" * 32)
    second = animation(tmp_path, version="c" * 32)
    item = list_resources("video_animation", "渐显", tmp_path)["resources"][0]
    assert item["cached"] is True
    assert item["path"] is None
    assert item["ready_to_reference"] is False
    assert item["cache_status"] == "multiple_cached_versions"
    assert {candidate["path"] for candidate in item["cache_candidates"]} == {str(first), str(second)}
    with pytest.raises(ValueError, match="multiple_cached_versions"):
        resolve_resource("video_animation", "渐显", tmp_path)


def test_package_path_traversal_is_rejected_before_reading_outside_file(tmp_path, monkeypatch):
    root = tmp_path / "effect"
    bundle = animation(root)
    secret = tmp_path / "private.txt"
    secret.write_text("do not read")
    (bundle / "content.json").write_text(json.dumps({"filemap": {"prefab": "../../../private.txt"}}))
    original_read_text = Path.read_text
    touched = []

    def record(self, *args, **kwargs):
        touched.append(self)
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", record)
    item = list_resources("video_animation", "渐显", root)["resources"][0]
    assert item["cached"] is False
    assert secret not in touched


@pytest.mark.parametrize("level", ["resource", "version", "payload"])
def test_cache_symlinks_never_establish_a_valid_package(tmp_path, level):
    root = tmp_path / "effect"
    outside = tmp_path / "outside"
    bundle = animation(outside)
    root.mkdir()
    if level == "resource":
        (root / VIDEO_FADE).symlink_to(outside / VIDEO_FADE, target_is_directory=True)
    elif level == "version":
        (root / VIDEO_FADE).mkdir()
        (root / VIDEO_FADE / ("a" * 32)).symlink_to(bundle, target_is_directory=True)
    else:
        local = animation(root)
        (local / "anim.prefab").unlink()
        (local / "anim.prefab").symlink_to(bundle / "anim.prefab")
    assert list_resources("video_animation", "渐显", root)["resources"][0]["cached"] is False


@pytest.mark.parametrize("content", ["not json", "[]", '{"value": NaN}', "x" * (1024 * 1024 + 1)])
def test_bad_or_oversized_metadata_does_not_break_other_entries(tmp_path, content):
    bundle = animation(tmp_path)
    (bundle / "config.json").write_text(content)
    transition(tmp_path)
    result = list_resources(cache_root=tmp_path)
    assert result["cached_count"] == 1
    assert resolve_resource("transition", "叠化", tmp_path)["cached"] is True


def test_listing_only_reads_allowlisted_effect_cache_paths(tmp_path, monkeypatch):
    effect = tmp_path / "effect"
    animation(effect)
    outside = tmp_path / "account-data"
    outside.mkdir()
    (outside / "config.json").write_text("private")
    original_read_text = Path.read_text
    touched = []

    def record(self, *args, **kwargs):
        touched.append(self)
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", record)
    list_resources(cache_root=effect)
    assert touched
    assert all(path.is_relative_to(effect) for path in touched)


@pytest.mark.parametrize("kind,query", [("unknown", ""), ([], ""), ("all", None), ("all", "\x00"), ("all", "a" * 201)])
def test_invalid_selectors_fail_explicitly(tmp_path, kind, query):
    with pytest.raises(ValueError):
        list_resources(kind=kind, query=query, cache_root=tmp_path)


def test_cache_root_must_be_absolute_and_not_a_symlink(tmp_path):
    with pytest.raises(ValueError):
        list_resources(cache_root="relative/effect")
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        list_resources(cache_root=link)
