"""Metadata reuse must preserve file freshness, caller isolation and concurrency."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Barrier, Event, Lock
import wave

import pytest

from jianying_local_mcp import media


@pytest.fixture(autouse=True)
def empty_cache():
    media._clear_probe_cache()
    yield
    media._clear_probe_cache()


def write_wav(path, frames=800):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\0\0" * frames)
    return path


@pytest.fixture
def source(tmp_path):
    return write_wav(tmp_path / "source.wav")


@pytest.fixture
def fake_probe(monkeypatch):
    calls = []

    def probe(path, executable):
        calls.append((path, executable))
        return {"path": str(path), "bytes": path.stat().st_size,
                "kind": "audio", "duration": 1.0}

    monkeypatch.setattr(media, "_probe_media_uncached", probe)
    return calls


def test_real_repeated_probe_runs_ffmpeg_once_and_returns_independent_results(source, monkeypatch):
    original = media.subprocess.run
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(media.subprocess, "run", counted)
    first = media.probe_media(str(source))
    expected = first.copy()
    first["path"] = "caller changed its result"
    first["duration"] = 100
    assert media.probe_media(str(source)) == expected
    assert media.probe_media(str(source.parent / "." / source.name)) == expected
    assert expected["duration"] == 0.1
    assert expected["duration_precision"] == 1 / 8000
    assert len(calls) == 1


def test_replaced_file_with_same_size_and_mtime_is_reprobed(source, fake_probe, tmp_path):
    media.probe_media(str(source))
    before = source.stat()
    replacement = write_wav(tmp_path / "replacement.wav")
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(source)
    assert source.stat().st_size == before.st_size
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    assert source.stat().st_ino != before.st_ino
    media.probe_media(str(source))
    assert len(fake_probe) == 2


def test_same_size_in_place_edit_with_restored_mtime_is_reprobed(source, fake_probe):
    media.probe_media(str(source))
    before = source.stat()
    with source.open("r+b") as handle:
        handle.seek(-1, os.SEEK_END)
        handle.write(b"\x01")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert source.stat().st_size == before.st_size
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    assert source.stat().st_ctime_ns != before.st_ctime_ns
    media.probe_media(str(source))
    assert len(fake_probe) == 2


def test_deleted_cached_source_is_rejected(source, fake_probe):
    media.probe_media(str(source))
    source.unlink()
    with pytest.raises(FileNotFoundError):
        media.probe_media(str(source))
    assert len(fake_probe) == 1


def test_symlink_alias_reuses_target_but_retargeting_invalidates(source, fake_probe, tmp_path):
    alias = tmp_path / "alias.wav"
    alias.symlink_to(source)
    assert media.probe_media(str(alias))["path"] == str(source)
    media.probe_media(str(source))
    assert len(fake_probe) == 1
    other = write_wav(tmp_path / "other.wav", frames=1600)
    alias.unlink()
    alias.symlink_to(other)
    assert media.probe_media(str(alias))["path"] == str(other)
    assert len(fake_probe) == 2


def test_executable_change_and_override_change_invalidate(source, fake_probe, tmp_path, monkeypatch):
    executable = tmp_path / "ffmpeg-one"
    executable.write_bytes(b"fake executable, probing is mocked")
    executable.chmod(0o700)
    monkeypatch.setenv("JIANYING_FFMPEG", str(executable))
    media.probe_media(str(source))
    media.probe_media(str(source))
    executable.write_bytes(b"a changed executable")
    media.probe_media(str(source))
    second = tmp_path / "ffmpeg-two"
    second.write_bytes(b"second executable")
    second.chmod(0o700)
    monkeypatch.setenv("JIANYING_FFMPEG", str(second))
    media.probe_media(str(source))
    assert [c[1] for c in fake_probe] == [str(executable), str(executable), str(second)]
    second.chmod(0o600)
    with pytest.raises(ValueError, match="executable file"):
        media.probe_media(str(source))


def test_failed_probe_is_not_cached(source, monkeypatch):
    calls = []

    def probe(path, executable):
        calls.append(path)
        if len(calls) == 1:
            raise ValueError("transient probe failure")
        return {"path": str(path)}

    monkeypatch.setattr(media, "_probe_media_uncached", probe)
    with pytest.raises(ValueError, match="transient probe failure"):
        media.probe_media(str(source))
    assert media.probe_media(str(source))["path"] == str(source)
    assert len(calls) == 2


def test_file_changed_during_probe_is_not_cached(source, monkeypatch):
    calls = []

    def probe(path, executable):
        calls.append(path)
        if len(calls) == 1:
            path.write_bytes(path.read_bytes() + b"changed")
        return {"path": str(path)}

    monkeypatch.setattr(media, "_probe_media_uncached", probe)
    with pytest.raises(ValueError, match="changed during metadata read"):
        media.probe_media(str(source))
    media.probe_media(str(source))
    assert len(calls) == 2


def test_parallel_same_file_requests_share_one_probe(source, monkeypatch):
    entered, release = Event(), Event()
    start, counter_lock = Barrier(7), Lock()
    calls = []

    def probe(path, executable):
        with counter_lock:
            calls.append(path)
        entered.set()
        assert release.wait(5)
        return {"path": str(path)}

    def request():
        start.wait(timeout=5)
        return media.probe_media(str(source))

    monkeypatch.setattr(media, "_probe_media_uncached", probe)
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = [pool.submit(request) for _ in range(6)]
        start.wait(timeout=5)
        assert entered.wait(5)
        release.set()
        results = [p.result(timeout=5) for p in pending]
    assert len(calls) == 1
    assert all(r == {"path": str(source)} for r in results)
    assert len({id(r) for r in results}) == 6


def test_different_files_can_probe_concurrently(source, tmp_path, monkeypatch):
    other = write_wav(tmp_path / "other.wav")
    both_inside_probe = Barrier(2)

    def probe(path, executable):
        both_inside_probe.wait(timeout=5)
        return {"path": str(path)}

    monkeypatch.setattr(media, "_probe_media_uncached", probe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(media.probe_media, [str(source), str(other)]))
    assert [r["path"] for r in results] == [str(source), str(other)]


def test_entries_expire_without_writing_cache_files(source, fake_probe, tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(media, "monotonic", lambda: clock[0])
    before = set(tmp_path.iterdir())
    media.probe_media(str(source))
    clock[0] = media._PROBE_CACHE_TTL - 1
    media.probe_media(str(source))
    assert len(fake_probe) == 1
    clock[0] = media._PROBE_CACHE_TTL
    media.probe_media(str(source))
    assert len(fake_probe) == 2
    assert set(tmp_path.iterdir()) == before


def test_lru_bound_keeps_recent_files_and_evicts_oldest(source, fake_probe, tmp_path, monkeypatch):
    monkeypatch.setattr(media, "_PROBE_CACHE_LIMIT", 2)
    second = write_wav(tmp_path / "second.wav")
    third = write_wav(tmp_path / "third.wav")
    for path in [source, second, source, third, source, second]:
        media.probe_media(str(path))
    assert [c[0] for c in fake_probe] == [source, second, third, second]
    assert len(media._PROBE_CACHE) == 2
