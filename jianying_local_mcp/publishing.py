"""Publish a managed revision as a new native Mac draft, with index backup.

Publishing is one-way: later edits made by Jianying are never pulled back into
the managed workspace, and an existing native project is never replaced.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unicodedata
from uuid import UUID, uuid4

from . import __version__
from .core import MANIFEST, MAX_JSON, ProjectStore, project_name, summarize
from .native import build_native

_INDEX = "root_meta_info.json"
_LOCK = ".jianying-mcp-publish.lock"


def _name_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _identity(path: Path) -> tuple[int, int]:
    current = path.lstat()
    return current.st_dev, current.st_ino


def _same_file(path: Path, identity: tuple[int, int]) -> bool:
    try:
        return not path.is_symlink() and _identity(path) == identity
    except FileNotFoundError:
        return False


def _exclusive_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, mode)
    created = os.fstat(descriptor)
    identity = (created.st_dev, created.st_ino)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if _same_file(path, identity):
            path.unlink()
        raise


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Native index contains duplicate JSON keys")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Native index contains an invalid JSON number")


def _read_index(path: Path) -> tuple[bytes, dict]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
        raise ValueError("Native root index must be a regular, non-symlink JSON file under 64 MB")
    original = path.read_bytes()
    try:
        data = json.loads(original.decode("utf-8-sig"), object_pairs_hook=_reject_duplicate_keys,
                          parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Native root index must be plaintext JSON; no decryption is attempted") from exc
    if not isinstance(data, dict) or not isinstance(data.get("all_draft_store"), list):
        raise ValueError("Unknown native index structure: all_draft_store must be a list")
    for entry in data["all_draft_store"]:
        if not isinstance(entry, dict) or any(not isinstance(entry.get(key), str)
                                             for key in ("draft_id", "draft_name", "draft_fold_path")):
            raise ValueError("Unknown native draft entry structure")
    ids = data.get("draft_ids")
    if isinstance(ids, bool) or not isinstance(ids, (int, list)):
        raise ValueError("Unknown draft_ids structure; index was not changed")
    if isinstance(ids, int):
        if ids < 0:
            raise ValueError("Unknown negative draft_ids value")
    else:
        # A list is supported only when it unambiguously enumerates the entry IDs.
        if (not all(isinstance(value, str) and value for value in ids)
                or len({value.casefold() for value in ids}) != len(ids)
                or {value.casefold() for value in ids}
                != {entry["draft_id"].casefold() for entry in data["all_draft_store"]}):
            raise ValueError("Unknown draft_ids list semantics; index was not changed")
    return original, data


def _ensure_app_closed() -> None:
    """Read process names only; failure to verify is a refusal, not permission."""
    try:
        result = subprocess.run(["/bin/ps", "-axo", "comm="], check=True,
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Could not verify that Jianying is closed; publication refused") from exc
    if not result.stdout.strip():
        raise RuntimeError("Empty process inspection; publication refused")
    main_names = {"jianyingpro", "jianying", "videofusion-macos", "剪映专业版", "剪映"}
    if any(Path(line.strip()).name.casefold() in main_names for line in result.stdout.splitlines()):
        raise RuntimeError("Jianying is running; fully quit the app before publishing")


def _check_available(root: Path, target: Path, data: dict, name: str, draft_id: str) -> None:
    if target.exists() or target.is_symlink():
        raise ValueError("Native project already exists; publish a new managed revision name")
    if any(_name_key(item.name) == _name_key(name) for item in root.iterdir()):
        raise ValueError("Native directory name already exists under Unicode/case normalization")
    for entry in data["all_draft_store"]:
        if (_name_key(entry["draft_name"]) == _name_key(name)
                or entry["draft_id"].casefold() == draft_id.casefold()
                or (entry["draft_fold_path"] and Path(entry["draft_fold_path"]).absolute() == target)):
            raise ValueError("Native index already contains this project name, path, or ID")


def _collect_media(plan: dict, source_dir: Path, target: Path) -> tuple[list[tuple[Path, str]], int]:
    resources = source_dir / "Resources"
    if resources.is_symlink() or not resources.is_dir():
        raise ValueError("Managed Resources must be an existing non-symlink directory")
    copies: dict[Path, str] = {}
    total = 0
    for clip in plan["clips"]:
        if clip.get("kind") == "text":
            continue
        raw = clip.get("path")
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise ValueError("Managed media must use absolute Resources paths")
        source = Path(raw)
        if ".." in source.parts:
            raise ValueError("Managed media cannot traverse directories")
        try:
            resolved_source = source.resolve(strict=True)
            resolved_source.relative_to(resources)
        except ValueError as exc:
            raise ValueError("Managed media must be inside this project's Resources") from exc
        # Resolve system aliases such as /var -> /private/var, but refuse links
        # inside or substituting the managed Resources subtree itself.
        cursor = source
        while cursor.resolve(strict=True) != resources:
            if cursor.is_symlink():
                raise ValueError("Symlinked managed media is not supported")
            cursor = cursor.parent
        if cursor.is_symlink():
            raise ValueError("Symlinked managed Resources is not supported")
        source = resolved_source
        if not source.is_file() or not stat.S_ISREG(source.stat().st_mode):
            raise ValueError("Managed media must be a regular local file")
        if source not in copies:
            total += source.stat().st_size
            if total > 10 * 1024**3:
                raise ValueError("Publication is limited to 10 GB of bundled media")
            extension = source.suffix.lower()
            if len(extension) > 16 or any(not (c.isalnum() or c == ".") for c in extension):
                raise ValueError("Unsupported media filename extension")
            copies[source] = f"{len(copies) + 1:04d}{extension}"
        clip["path"] = str(target / "Resources" / copies[source])
    return list(copies.items()), total


def _copy_media(source: Path, target: Path) -> None:
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as incoming:
        before = os.fstat(incoming.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Managed media changed into a nonregular file")
        with target.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        after = os.fstat(incoming.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError("Managed media changed during publication; retry with a stable revision")


def publish_project(store: ProjectStore, name: str, draft_root: str, dry_run: bool = True) -> dict:
    """Publish only a fresh directory and append exactly one native index entry.

    A tool-only lock coordinates our publishers; a SHA256 check detects other
    index writers. The app is checked before copying and immediately before
    index commit. The caller must keep it closed until this function returns.
    """
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be boolean")
    name = project_name(name)
    root = Path(draft_root)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("draft_root must be an absolute existing directory")
    root = root.resolve(strict=True)
    target = root / name
    index_path = root / _INDEX
    original, data = _read_index(index_path)
    original_sha = hashlib.sha256(original).hexdigest()
    plan = deepcopy(store.load_managed(name))
    if plan.get("name") != name:
        raise ValueError("Managed manifest name does not match the selected revision")
    draft_id = str(UUID(plan["id"])).upper()
    _check_available(root, target, data, name, draft_id)
    source_dir = store.workspace / name
    copies, total = _collect_media(plan, source_dir, target)
    files = build_native(plan, target)
    now = datetime.now(timezone.utc)
    now_us = int(now.timestamp() * 1_000_000)
    files["draft_meta_info.json"].update(
        tm_draft_create=now_us, tm_draft_modified=now_us, draft_timeline_materials_size_=total)
    entry = {
        "draft_id": draft_id, "draft_name": name, "draft_fold_path": str(target),
        "draft_root_path": str(root), "draft_json_file": str(target / "draft_info.json"),
        "draft_cover": "", "draft_is_invisible": False, "draft_type": "",
        "draft_new_version": "", "streaming_edit_draft_ready": True,
        "draft_timeline_materials_size": total, "tm_duration": files["draft_info.json"]["duration"],
        "tm_draft_create": now_us, "tm_draft_modified": now_us, "tm_draft_removed": 0,
    }
    updated = deepcopy(data)
    updated["all_draft_store"].append(entry)
    ids_action = "preserved_application_integer"
    if isinstance(updated["draft_ids"], list):
        updated["draft_ids"].append(draft_id)
        ids_action = "appended_to_verified_id_list"
    result = {
        "status": "ready_to_publish" if dry_run else "published", "dry_run": dry_run,
        "summary": summarize(plan), "native_project_dir": str(target), "draft_id": draft_id,
        "media_files": len(copies), "media_bytes": total, "index_sha256_before": original_sha,
        "draft_ids_action": ids_action, "native_app_verified": False,
        "publication_mode": "one_way_new_project", "requires_app_closed": True,
        "note": "Native edits after publication are not synchronized back to the managed revision.",
    }
    if dry_run:
        result["index_entry"] = entry
        return result

    _ensure_app_closed()
    token = uuid4().hex
    lock = root / _LOCK
    try:
        _exclusive_write(lock, _json_bytes({"pid": os.getpid(), "operation": token}))
    except FileExistsError as exc:
        raise RuntimeError("Another publication lock exists; no native files were changed") from exc
    lock_identity = _identity(lock)
    staging = None
    staging_identity = None
    created_identity = None
    index_temp_identity = None
    index_temp = root / f".root_meta_info.{token}.tmp"
    committed = False
    try:
        current, fresh = _read_index(index_path)
        if hashlib.sha256(current).hexdigest() != original_sha:
            raise RuntimeError("Native index changed since validation; publication refused")
        _check_available(root, target, fresh, name, draft_id)
        staging = Path(tempfile.mkdtemp(prefix=".jianying-mcp-staging-", dir=root))
        staging_identity = _identity(staging)
        (staging / "Resources").mkdir()
        for source, filename in copies:
            _copy_media(source, staging / "Resources" / filename)
        for filename, payload in files.items():
            _exclusive_write(staging / filename, _json_bytes(payload))
        manifest = {
            "format": "jianying-local-mcp", "format_version": 1, "tool_version": __version__,
            "created_at": now.isoformat(), "native_app_verified": False, "plan": plan,
            "publication": {"mode": "one_way_new_project", "source_project_name": name,
                            "operation": token, "managed_project_id": plan["id"]},
        }
        _exclusive_write(staging / MANIFEST, _json_bytes(manifest))
        target.mkdir(exist_ok=False)
        created_identity = _identity(target)
        for item in staging.iterdir():
            shutil.move(str(item), str(target / item.name))

        _ensure_app_closed()
        current, _ = _read_index(index_path)
        if hashlib.sha256(current).hexdigest() != original_sha:
            raise RuntimeError("Native index changed during publication; new directory will be rolled back")
        backup_dir = root / ".jianying-mcp-backups"
        if backup_dir.is_symlink():
            raise ValueError("Native index backup directory cannot be a symlink")
        backup_dir.mkdir(exist_ok=True, mode=0o700)
        backup = backup_dir / f"root_meta_info.{now.strftime('%Y%m%dT%H%M%S')}.{token}.json.bak"
        _exclusive_write(backup, original)
        _exclusive_write(index_temp, _json_bytes(updated))
        index_temp_identity = _identity(index_temp)
        current, _ = _read_index(index_path)
        if hashlib.sha256(current).hexdigest() != original_sha:
            raise RuntimeError("Native index changed before commit; publication refused")
        os.replace(index_temp, index_path)
        committed = True
        result["index_backup"] = str(backup)
        result["index_sha256_after"] = hashlib.sha256(_json_bytes(updated)).hexdigest()
        return result
    finally:
        try:
            if not committed and created_identity and _same_file(target, created_identity):
                shutil.rmtree(target)
        finally:
            try:
                if staging is not None and staging_identity and _same_file(staging, staging_identity):
                    shutil.rmtree(staging, ignore_errors=True)
                if index_temp_identity and _same_file(index_temp, index_temp_identity):
                    index_temp.unlink()
            finally:
                if _same_file(lock, lock_identity):
                    lock.unlink()
