"""Publishing tests use temporary native roots only; no installed app is touched."""

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from jianying_local_mcp.core import MANIFEST, ProjectStore
from jianying_local_mcp.publishing import _ensure_app_closed, publish_project


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.workspace = self.base / "workspace"
        self.source = self.workspace / "New test"
        (self.source / "Resources").mkdir(parents=True)
        self.media = self.source / "Resources" / "clip.mp4"
        self.media.write_bytes(b"synthetic media fixture")
        self.plan = {
            "id": "046a7d5c-f4b2-4e98-a7aa-345c9f48b82e", "name": "New test",
            "width": 1920, "height": 1080, "fps": 30,
            "clips": [{"id": "v", "kind": "video", "track": "V1", "start": 0,
                       "duration": 2, "path": str(self.media), "media_duration": 3,
                       "media_width": 1920, "media_height": 1080, "has_audio": True}],
        }
        self.manifest = {"format": "jianying-local-mcp", "format_version": 1, "plan": self.plan}
        (self.source / MANIFEST).write_text(json.dumps(self.manifest))
        self.root = self.base / "native"
        self.root.mkdir()
        self.old_entry = {"draft_id": "older-id", "draft_name": "Existing",
                          "draft_fold_path": str(self.root / "Existing"),
                          "unknown_nested": {"tokens": [1, {"value": "preserve"}]}}
        self.index = {"all_draft_store": [self.old_entry], "draft_ids": 910,
                      "unknown_root": {"keep": [False, None, "unchanged"]}}
        self.index_path = self.root / "root_meta_info.json"
        self.write_index()
        self.store = ProjectStore(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def write_index(self):
        self.index_path.write_text(json.dumps(self.index, indent=1))

    def publish(self, dry_run=False):
        return publish_project(self.store, "New test", str(self.root), dry_run=dry_run)

    def test_dry_run_writes_nothing_and_preserves_source(self):
        before = {str(p.relative_to(self.base)): p.read_bytes()
                  for p in self.base.rglob("*") if p.is_file()}
        with patch("jianying_local_mcp.publishing._ensure_app_closed") as app_check:
            result = self.publish(dry_run=True)
        after = {str(p.relative_to(self.base)): p.read_bytes()
                 for p in self.base.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(result["status"], "ready_to_publish")
        app_check.assert_not_called()
        self.assertFalse((self.root / "New test").exists())

    @patch("jianying_local_mcp.publishing._ensure_app_closed")
    def test_publish_appends_one_entry_keeps_unknown_data_and_exact_backup(self, _check):
        original = self.index_path.read_bytes()
        source_manifest = (self.source / MANIFEST).read_bytes()
        result = self.publish()
        written = json.loads(self.index_path.read_text())
        self.assertEqual(written["all_draft_store"][:-1], [self.old_entry])
        self.assertEqual(written["unknown_root"], self.index["unknown_root"])
        self.assertEqual(written["draft_ids"], 910)
        self.assertEqual(Path(result["index_backup"]).read_bytes(), original)
        self.assertEqual((self.source / MANIFEST).read_bytes(), source_manifest)
        target = self.root / "New test"
        self.assertEqual((target / "Resources" / "0001.mp4").read_bytes(), self.media.read_bytes())
        info = json.loads((target / "draft_info.json").read_text())
        self.assertEqual(info["materials"]["videos"][0]["path"], str(target / "Resources" / "0001.mp4"))
        self.assertEqual(written["all_draft_store"][-1]["draft_id"], info["id"])
        self.assertEqual(json.loads((target / MANIFEST).read_text())["publication"]["mode"], "one_way_new_project")
        self.assertFalse((self.root / ".jianying-mcp-publish.lock").exists())
        self.assertFalse(list(self.root.glob(".jianying-mcp-staging-*")))
        self.assertEqual(_check.call_count, 2)

    @patch("jianying_local_mcp.publishing._ensure_app_closed")
    def test_known_id_list_is_extended(self, _check):
        self.index["draft_ids"] = ["older-id"]
        self.write_index()
        result = self.publish()
        written = json.loads(self.index_path.read_text())
        self.assertEqual(written["draft_ids"], ["older-id", result["draft_id"]])

    def test_unknown_index_types_are_refused(self):
        for invalid in (True, None, {}, ["unrelated"], -1):
            with self.subTest(invalid=invalid):
                self.index["draft_ids"] = invalid
                self.write_index()
                before = self.index_path.read_bytes()
                with self.assertRaises(ValueError):
                    self.publish(dry_run=True)
                self.assertEqual(self.index_path.read_bytes(), before)

    def test_running_app_and_failed_inspection_do_not_write(self):
        original = self.index_path.read_bytes()
        with patch("jianying_local_mcp.publishing._ensure_app_closed", side_effect=RuntimeError("running")):
            with self.assertRaises(RuntimeError):
                self.publish()
        self.assertEqual(self.index_path.read_bytes(), original)
        self.assertEqual({p.name for p in self.root.iterdir()}, {"root_meta_info.json"})
        for output in ("/Applications/JianyingPro.app/Contents/MacOS/JianyingPro\n",
                       "/Applications/VideoFusion-macOS.app/Contents/MacOS/VideoFusion-macOS\n",
                       "/Applications/VideoFusion-macOS.app/Contents/Frameworks/VideoFusion-macOS.app/Contents/MacOS/VideoFusion-macOS\n",
                       ""):
            with patch("jianying_local_mcp.publishing.subprocess.run", return_value=subprocess.CompletedProcess([], 0, output, "")):
                with self.assertRaises(RuntimeError):
                    _ensure_app_closed()
        with patch("jianying_local_mcp.publishing.subprocess.run", side_effect=subprocess.TimeoutExpired("ps", 10)):
            with self.assertRaises(RuntimeError):
                _ensure_app_closed()

    @patch("jianying_local_mcp.publishing._ensure_app_closed")
    def test_duplicate_native_directory_name_or_id_is_refused(self, _check):
        for condition in ("directory", "name", "id"):
            with self.subTest(condition=condition):
                entry = copy.deepcopy(self.old_entry)
                target = self.root / "New test"
                if condition == "directory":
                    target.mkdir()
                    (target / "user-data").write_text("keep")
                elif condition == "name":
                    entry["draft_name"] = "NEW TEST"
                else:
                    entry["draft_id"] = self.plan["id"].upper()
                self.index["all_draft_store"] = [entry]
                self.write_index()
                with self.assertRaises(ValueError):
                    self.publish()
                if condition == "directory":
                    self.assertEqual((target / "user-data").read_text(), "keep")
                    (target / "user-data").unlink()
                    target.rmdir()

    @patch("jianying_local_mcp.publishing._ensure_app_closed")
    def test_commit_failure_rolls_back_only_new_directory(self, _check):
        existing = self.root / "Existing"
        existing.mkdir()
        (existing / "keep").write_bytes(b"user content")
        original = self.index_path.read_bytes()
        with patch("jianying_local_mcp.publishing.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(self.index_path.read_bytes(), original)
        self.assertEqual((existing / "keep").read_bytes(), b"user content")
        self.assertFalse((self.root / "New test").exists())
        self.assertFalse((self.root / ".jianying-mcp-publish.lock").exists())

    def test_concurrent_index_change_is_preserved_and_new_directory_removed(self):
        calls = 0
        changed = None
        def check():
            nonlocal calls, changed
            calls += 1
            if calls == 2:
                self.index["concurrent_data"] = "other writer"
                self.write_index()
                changed = self.index_path.read_bytes()
        with patch("jianying_local_mcp.publishing._ensure_app_closed", side_effect=check):
            with self.assertRaisesRegex(RuntimeError, "changed during"):
                self.publish()
        self.assertEqual(self.index_path.read_bytes(), changed)
        self.assertFalse((self.root / "New test").exists())

    def test_app_starting_before_commit_rolls_back_without_touching_index(self):
        original = self.index_path.read_bytes()
        with patch("jianying_local_mcp.publishing._ensure_app_closed",
                   side_effect=[None, RuntimeError("app started")]):
            with self.assertRaisesRegex(RuntimeError, "app started"):
                self.publish()
        self.assertEqual(self.index_path.read_bytes(), original)
        self.assertFalse((self.root / "New test").exists())
        self.assertFalse((self.root / ".jianying-mcp-publish.lock").exists())

    @patch("jianying_local_mcp.publishing._ensure_app_closed")
    def test_lock_write_failure_removes_only_its_own_partial_file(self, _check):
        original = self.index_path.read_bytes()
        with patch("jianying_local_mcp.publishing.os.fsync", side_effect=OSError("cannot sync")):
            with self.assertRaisesRegex(OSError, "cannot sync"):
                self.publish()
        self.assertEqual(self.index_path.read_bytes(), original)
        self.assertFalse((self.root / ".jianying-mcp-publish.lock").exists())
        self.assertFalse((self.root / "New test").exists())

    @patch("jianying_local_mcp.publishing._ensure_app_closed")
    def test_existing_lock_refuses_without_deleting_someone_elses_lock(self, _check):
        lock = self.root / ".jianying-mcp-publish.lock"
        lock.write_text("other publisher")
        with self.assertRaisesRegex(RuntimeError, "lock exists"):
            self.publish()
        self.assertEqual(lock.read_text(), "other publisher")
        self.assertFalse((self.root / "New test").exists())

    def test_outside_or_symlink_media_and_nonplaintext_index_are_rejected(self):
        outside = self.base / "outside.mp4"
        outside.write_bytes(b"outside")
        for media_path in (str(outside), str(self.source / "Resources" / "link.mp4")):
            if "link.mp4" in media_path:
                Path(media_path).symlink_to(outside)
            self.plan["clips"][0]["path"] = media_path
            (self.source / MANIFEST).write_text(json.dumps(self.manifest))
            with self.assertRaises(ValueError):
                self.publish(dry_run=True)
        self.index_path.write_text("encrypted-index")
        with self.assertRaisesRegex(ValueError, "plaintext"):
            self.publish(dry_run=True)


if __name__ == "__main__":
    unittest.main()
