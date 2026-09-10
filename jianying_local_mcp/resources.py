"""Read-only discovery of a small audited Jianying effect-resource catalog.

Names, IDs and default durations below were checked against pyJianYingDraft
metadata on 2026-09-09. Upstream attribution: Copyright 2024 Gary Guan,
Apache-2.0, https://github.com/GuanYixuan/pyJianYingDraft/blob/main/LICENSE.
These are factual catalog references, not copies of effect assets. Local
scripts, scenes and shaders are never executed, copied or downloaded here.

Catalog availability and is_vip are not a current account entitlement check.
Cache validation proves only the known resource directory and package structure,
not that an arbitrary resource was tested in the native application.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re


_SOURCE_ROOT = "https://github.com/GuanYixuan/pyJianYingDraft/blob/main/pyJianYingDraft/metadata/"
_LICENSE_URL = "https://github.com/GuanYixuan/pyJianYingDraft/blob/main/LICENSE"
_MAX_METADATA_BYTES = 1024 * 1024
_MAX_VERSIONS = 32
_KINDS = {"all", "animation", "video_animation", "text_animation", "transition"}

# Deliberately retain upstream names. 推移 is a search alias for directional
# transitions, not an invented official effect name or guessed resource ID.
_CATALOG = (
    {"name": "渐显", "kind": "video_animation", "animation_type": "in",
     "resource_id": "6798320778182922760", "effect_id": "624705",
     "default_duration": 0.5, "source_file": "video_intro.py", "aliases": ["视频渐显", "fade in"]},
    {"name": "渐隐", "kind": "video_animation", "animation_type": "out",
     "resource_id": "6798320902548230669", "effect_id": "624707",
     "default_duration": 0.5, "source_file": "video_outro.py", "aliases": ["视频渐隐", "fade out"]},
    {"name": "渐显", "kind": "text_animation", "animation_type": "in",
     "resource_id": "6724916044072227332", "effect_id": "1644304",
     "default_duration": 0.5, "source_file": "text_intro.py", "aliases": ["文字渐显", "字幕渐显"]},
    {"name": "渐隐", "kind": "text_animation", "animation_type": "out",
     "resource_id": "6724919382104871427", "effect_id": "1644600",
     "default_duration": 0.5, "source_file": "text_outro.py", "aliases": ["文字渐隐", "字幕渐隐"]},
    {"name": "叠化", "kind": "transition", "resource_id": "6724845717472416269", "effect_id": "322577",
     "default_duration": 0.5, "is_overlap": True, "source_file": "transition_meta.py", "aliases": ["dissolve"]},
    {"name": "左移", "kind": "transition", "resource_id": "6726711499676455435", "effect_id": "2917286",
     "default_duration": 1.0, "is_overlap": True, "source_file": "transition_meta.py", "aliases": ["推移", "左推", "push left"]},
    {"name": "右移", "kind": "transition", "resource_id": "6726711296063967748", "effect_id": "2917287",
     "default_duration": 1.0, "is_overlap": True, "source_file": "transition_meta.py", "aliases": ["推移", "右推", "push right"]},
)


def _cache_path(cache_root: str | Path | None) -> Path:
    if cache_root is None:
        raw = Path.home() / "Movies/JianyingPro/User Data/Cache/effect"
    elif isinstance(cache_root, (str, Path)):
        raw = Path(cache_root).expanduser()
    else:
        raise ValueError("cache_root must be an absolute effect-cache directory")
    if not raw.is_absolute() or "\x00" in str(raw) or ".." in raw.parts:
        raise ValueError("cache_root must be an absolute effect-cache directory without traversal")
    if raw.is_symlink():
        raise ValueError("cache_root cannot be a symlink")
    root = raw.resolve()
    if root.exists() and not root.is_dir():
        raise ValueError("cache_root must be a directory")
    return root


def _inside(directory: Path, relative: str, *, file: bool) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise ValueError("Invalid effect-package relative path")
    rel = Path(relative)
    if rel.is_absolute() or any(part in {"..", "."} for part in rel.parts):
        raise ValueError("Effect-package path cannot leave its directory")
    current = directory
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Effect-package paths cannot be symlinks")
    if not current.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Effect-package path cannot leave its directory")
    if file:
        if not current.is_file() or current.stat().st_size == 0:
            raise ValueError("Effect-package file is missing or empty")
    elif not current.is_dir():
        raise ValueError("Effect-package directory is missing")
    return current


def _json(directory: Path, relative: str) -> dict:
    path = _inside(directory, relative, file=True)
    if path.stat().st_size > _MAX_METADATA_BYTES:
        raise ValueError("Effect metadata exceeds the 1 MB read limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"),
                           parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Effect metadata is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Effect metadata must be a JSON object")
    return value


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Nonfinite effect metadata: {value}")


def _validate_package(directory: Path, kind: str, resource_id: str, effect_id: str) -> dict:
    config = _json(directory, "config.json")
    for field, expected in (("resource_id", resource_id), ("effect_id", effect_id)):
        if field in config and str(config[field]) != expected:
            raise ValueError(f"Cached package {field} conflicts with the reviewed catalog")
    effect = config.get("effect")
    links = effect.get("Link") if isinstance(effect, dict) else None
    if not isinstance(links, list) or not links or any(not isinstance(link, dict) for link in links):
        raise ValueError("Effect config has no valid Link list")
    evidence = {"config_version": config.get("version"), "checked_files": ["config.json"]}
    if kind in {"video_animation", "text_animation"}:
        if not any(link.get("type") == "InfoSticker" for link in links):
            raise ValueError("Cached package does not have the supported animation structure")
        content = _json(directory, "content.json")
        filemap = content.get("filemap")
        if not isinstance(filemap, dict) or not isinstance(filemap.get("prefab"), str):
            raise ValueError("Animation content does not identify a prefab")
        prefab = filemap["prefab"]
        _inside(directory, prefab, file=True)
        evidence["checked_files"].extend(["content.json", prefab])
    else:
        linked = [link for link in links if link.get("type") == "AmazingFeature"]
        if not linked:
            raise ValueError("Cached package does not have the supported transition structure")
        package = _inside(directory, linked[0].get("path"), file=False)
        _json(package, "content.json")
        _inside(package, "main.scene", file=True)
        prefix = str(package.relative_to(directory))
        evidence["checked_files"].extend([f"{prefix}/content.json", f"{prefix}/main.scene"])
        if (directory / "extra.json").exists() or (directory / "extra.json").is_symlink():
            extra = _json(directory, "extra.json")
            transition = extra.get("transition")
            if isinstance(transition, dict):
                evidence["cached_transition_defaults"] = {key: transition[key] for key in ("defaultDura", "isOverlap") if key in transition}
            evidence["checked_files"].append("extra.json")
    return evidence


def _matches_kind(requested: str, actual: str) -> bool:
    return requested == "all" or requested == actual or (requested == "animation" and actual.endswith("_animation"))


def list_resources(kind: str = "all", query: str = "", cache_root: str | Path | None = None) -> dict:
    """List audited catalog entries and validate their already downloaded cache.

    cache_root is the effect directory itself, normally .../Cache/effect. Only
    seven known resource IDs are considered. This never scans account files,
    logs, personal drafts, onlineMaterial thumbnails, or resourcePanel data.
    Unrecognized cache directories do not become inferred catalog entries.
    ``cached`` and ``native_app_verified`` are deliberately separate claims.
    """
    if not isinstance(kind, str) or kind not in _KINDS:
        raise ValueError(f"kind must be one of {', '.join(sorted(_KINDS))}")
    if not isinstance(query, str) or len(query) > 200 or any(ord(char) < 32 for char in query):
        raise ValueError("query must be a string of at most 200 characters without controls")
    root = _cache_path(cache_root)
    entries = []
    for raw in _CATALOG:
        if not _matches_kind(kind, raw["kind"]):
            continue
        searchable = " ".join([raw["name"], raw["resource_id"], raw["effect_id"], *raw["aliases"]]).casefold()
        if query.strip().casefold() not in searchable:
            continue
        item = deepcopy(raw)
        source_file = item.pop("source_file")
        item.update(catalog_source=_SOURCE_ROOT + source_file, catalog_checked_on="2026-09-09",
                    source_license="Apache-2.0", source_license_url=_LICENSE_URL,
                    is_vip=False, free_status="free_in_catalog", entitlement_verified=False,
                    native_app_verified=False, path=None, cached=False, cache_status="not_cached",
                    ready_to_reference=False, cache_candidates=[])
        parent = root / item["resource_id"]
        rejected = []
        if parent.is_symlink():
            item["cache_status"] = "unsafe_symlink"
        elif parent.is_dir():
            candidates = sorted((child for child in parent.iterdir() if re.fullmatch(r"[0-9a-fA-F]{32}", child.name)), key=lambda child: child.name)
            if len(candidates) > _MAX_VERSIONS:
                item["cache_status"] = "too_many_versions"
            else:
                for candidate in candidates:
                    try:
                        if candidate.is_symlink() or not candidate.is_dir():
                            raise ValueError("Cache version is not a regular directory")
                        evidence = _validate_package(candidate, item["kind"], item["resource_id"], item["effect_id"])
                        item["cache_candidates"].append({"path": str(candidate), "evidence": evidence})
                    except (ValueError, OSError) as exc:
                        rejected.append({"version": candidate.name, "reason": str(exc)})
                matches = item["cache_candidates"]
                item["cached"] = bool(matches)
                if len(matches) == 1:
                    item.update(path=matches[0]["path"], ready_to_reference=True,
                                cache_status="catalog_id_and_package_structure_match")
                elif matches:
                    item["cache_status"] = "multiple_cached_versions"
                else:
                    item["cache_status"] = "no_valid_cached_package"
        if rejected:
            item["rejected_candidates"] = rejected
        entries.append(item)
    return {"cache_root": str(root), "cache_root_exists": root.is_dir(), "kind": kind, "query": query,
            "coverage": "small_reviewed_catalog_only", "count": len(entries),
            "cached_count": sum(item["cached"] for item in entries), "resources": entries,
            "notes": ["Cache presence is not native playback verification or current account entitlement.",
                      "Effect assets are referenced locally; no scripts execute and no resources download."]}


def resolve_resource(kind: str, name: str, cache_root: str | Path | None = None) -> dict:
    """Resolve one named, catalog-free resource with one valid cached version."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Resource name must be a nonempty string")
    listing = list_resources(kind=kind, query=name, cache_root=cache_root)
    wanted = name.strip().casefold()
    matches = [item for item in listing["resources"] if wanted == item["name"].casefold()
               or wanted in {alias.casefold() for alias in item["aliases"]}
               or wanted in {item["resource_id"], item["effect_id"]}]
    if len(matches) != 1:
        raise ValueError("Resource name must identify exactly one reviewed catalog entry; specify its kind and exact name")
    item = matches[0]
    if item["is_vip"] is not False:
        raise ValueError("Only resources explicitly marked free in the reviewed catalog can be resolved automatically")
    if not item["ready_to_reference"] or not item["cached"] or not item["path"]:
        raise ValueError(f"Resource has no unique validated local cache: {item['cache_status']}")
    return item
