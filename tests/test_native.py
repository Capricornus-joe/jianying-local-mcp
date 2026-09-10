"""Structural tests; these do not claim a Jianying application smoke test."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jianying_local_mcp.native import build_native


def example_plan():
    return {
        "id": "551a9ef2-5a4a-4b6e-9cbe-854f918f345f", "name": "Synthetic test",
        "width": 1920, "height": 1080, "fps": 30,
        "clips": [
            {"id": "a", "kind": "video", "track": "V1", "start": 1.25,
             "duration": 2, "source_start": 3, "speed": 2, "volume": 0,
             "path": "/example/Resources/video.mp4", "media_duration": 20,
             "media_width": 1920, "media_height": 1080, "has_audio": True},
            {"id": "b", "kind": "video", "track": "V1", "start": 4.25,
             "duration": 3, "source_start": 10, "speed": 0.5,
             "path": "/example/Resources/video.mp4", "media_duration": 20,
             "media_width": 1920, "media_height": 1080, "has_audio": True},
            {"id": "music", "kind": "audio", "track": "A1", "start": 0,
             "duration": 8, "source_start": 0.5, "volume": 0.25,
             "path": "/example/Resources/music.wav", "media_duration": 40},
            {"id": "title", "kind": "text", "track": "T1", "start": 0.5,
             "duration": 5, "text": "测试标题\n可继续编辑", "font_size": 48,
             "color": "#F08020", "x": 0.1, "y": -0.7},
        ],
    }


class NativeDraftTests(unittest.TestCase):
    def build(self, plan=None):
        return build_native(plan or example_plan(), Path("/example/project"))

    def test_video_audio_and_text_preserve_timing_and_content(self):
        files = self.build()
        self.assertEqual(set(files), {"draft_info.json", "draft_meta_info.json"})
        info = files["draft_info.json"]
        self.assertEqual(info["duration"], 8_000_000)
        self.assertEqual([t["type"] for t in info["tracks"]], ["video", "audio", "text"])
        first, second = info["tracks"][0]["segments"]
        self.assertEqual(first["source_timerange"], {"start": 3_000_000, "duration": 4_000_000})
        self.assertEqual(first["target_timerange"], {"start": 1_250_000, "duration": 2_000_000})
        self.assertEqual(second["source_timerange"]["duration"], 1_500_000)
        self.assertEqual(first["volume"], 0)
        audio = info["tracks"][1]["segments"][0]
        self.assertIsNone(audio["clip"])
        self.assertEqual(audio["volume"], 0.25)
        text = info["materials"]["texts"][0]
        content = json.loads(text["content"])
        self.assertEqual(content["text"], example_plan()["clips"][-1]["text"])
        self.assertEqual(content["styles"][0]["size"], 8)
        self.assertEqual(content["styles"][0]["range"], [0, len(content["text"])])
        caption = info["tracks"][2]["segments"][0]
        self.assertIsNone(caption["source_timerange"])
        self.assertEqual(caption["clip"]["transform"], {"x": 0.1, "y": -0.7})
        self.assertGreater(caption["render_index"], first["render_index"])

    def test_every_segment_reference_resolves_and_media_is_registered(self):
        files = self.build()
        info, meta = files["draft_info.json"], files["draft_meta_info.json"]
        material_ids = [m["id"] for group in info["materials"].values() for m in group]
        self.assertEqual(len(material_ids), len(set(material_ids)))
        for track in info["tracks"]:
            for segment in track["segments"]:
                self.assertIn(segment["material_id"], material_ids)
                self.assertTrue(set(segment["extra_material_refs"]).issubset(material_ids))
        # The two cuts share one video material, so the media pool has two files.
        records = next(g["value"] for g in meta["draft_materials"] if g["type"] == 0)
        self.assertEqual(len(records), 2)
        self.assertEqual({r["metetype"] for r in records}, {"video", "music"})
        for visual in info["materials"]["videos"]:
            self.assertEqual(visual["material_id"], visual["id"])
            for field in ("local_material_id", "local_id", "origin_material_id"):
                self.assertEqual(visual[field], "")
        self.assertTrue({r["id"] for r in records}.isdisjoint(material_ids))
        media_paths = {m["path"] for group in ("videos", "audios") for m in info["materials"][group]}
        self.assertEqual({r["file_Path"] for r in records}, media_paths)
        self.assertEqual(meta["draft_id"], info["id"])
        self.assertEqual(meta["tm_duration"], info["duration"])

    def test_stills_use_three_hour_materials_without_extending_segments(self):
        plan = example_plan()
        image = {
            "id": "photo1", "kind": "image", "track": "V2", "start": 0.4,
            "duration": 0.32, "path": "/example/Resources/still.png", "media_duration": 0.04,
            "media_width": 800, "media_height": 600,
        }
        plan["clips"].extend([image, {**image, "id": "photo2", "start": 3, "duration": 6}])
        files = self.build(plan)
        info = files["draft_info.json"]
        photos = [m for m in info["materials"]["videos"] if m["type"] == "photo"]
        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]["material_id"], photos[0]["id"])
        self.assertEqual(photos[0]["duration"], 10_800_000_000)
        self.assertFalse(photos[0]["has_audio"])
        records = files["draft_meta_info.json"]["draft_materials"][0]["value"]
        record = next(r for r in records if r["metetype"] == "photo")
        self.assertEqual(record["duration"], 10_800_000_000)
        segments = next(t for t in info["tracks"] if t["name"] == "V2")["segments"]
        self.assertEqual(segments[0]["source_timerange"], {"start": 0, "duration": 320_000})
        self.assertEqual(segments[0]["target_timerange"], {"start": 400_000, "duration": 320_000})
        self.assertEqual(segments[1]["source_timerange"]["duration"], 6_000_000)
        self.assertEqual(info["duration"], 9_000_000)
        self.assertEqual(files["draft_meta_info.json"]["tm_duration"], 9_000_000)
        self.assertEqual(next(m for m in info["materials"]["videos"] if m["type"] == "video")["duration"], 20_000_000)
        self.assertEqual(info["materials"]["audios"][0]["duration"], 40_000_000)

    def test_media_display_names_are_independent_for_repeated_source_files(self):
        for kind in ("video", "image", "audio"):
            with self.subTest(kind=kind):
                plan = example_plan()
                clip = {**plan["clips"][0], "kind": kind, "start": 0,
                        "source_start": 0, "speed": 1, "duration": 1}
                plan["clips"] = [
                    {**clip, "id": "first", "display_name": "01_走近_舞台"},
                    {**clip, "id": "second", "start": 1, "display_name": "字" * 120},
                    {**clip, "id": "third", "start": 2, "display_name": "01_走近_舞台"},
                ]
                files = self.build(plan)
                info = files["draft_info.json"]
                group = "audios" if kind == "audio" else "videos"
                name_field = "name" if kind == "audio" else "material_name"
                materials = {m["id"]: m for m in info["materials"][group]}
                segments = info["tracks"][0]["segments"]
                self.assertEqual(len(materials), 2)
                self.assertEqual([materials[s["material_id"]][name_field] for s in segments],
                                 [c["display_name"] for c in plan["clips"]])
                self.assertEqual({m["path"] for m in materials.values()}, {clip["path"]})
                records = files["draft_meta_info.json"]["draft_materials"][0]["value"]
                self.assertEqual({r["extra_info"] for r in records}, {"01_走近_舞台", "字" * 120})
                self.assertEqual({r["file_Path"] for r in records}, {clip["path"]})

    def test_image_material_keeps_source_ranges_longer_than_three_hours(self):
        image = {
            "kind": "image", "track": "V2", "source_start": 0,
            "path": "/example/Resources/still.png", "media_duration": 0.04,
            "media_width": 800, "media_height": 600,
        }
        for durations in ((0.32, 10801), (10801, 0.32)):
            with self.subTest(durations=durations):
                plan = example_plan()
                plan["clips"].extend([
                    {**image, "id": "photo1", "start": 0, "duration": durations[0]},
                    {**image, "id": "photo2", "start": durations[0] + 1, "duration": durations[1]},
                ])
                files = self.build(plan)
                material = next(m for m in files["draft_info.json"]["materials"]["videos"] if m["type"] == "photo")
                record = next(r for r in files["draft_meta_info.json"]["draft_materials"][0]["value"] if r["metetype"] == "photo")
                self.assertEqual(material["duration"], 10_801_000_000)
                self.assertEqual(record["duration"], material["duration"])

    def test_no_io_no_input_mutation_and_no_device_identifiers(self):
        plan = example_plan()
        before = copy.deepcopy(plan)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "not-created"
            with patch("builtins.open", side_effect=AssertionError("unexpected file read")), \
                 patch.object(Path, "read_text", side_effect=AssertionError("unexpected draft read")), \
                 patch.object(Path, "stat", side_effect=AssertionError("unexpected file probe")):
                files = build_native(plan, target)
            self.assertFalse(target.exists())
        self.assertEqual(plan, before)
        self.assertEqual(files["draft_info.json"]["platform"]["os"], "mac")
        for platform in ("platform", "last_modified_platform"):
            for key in ("device_id", "hard_disk_id", "mac_address"):
                self.assertEqual(files["draft_info.json"][platform][key], "")
        json.dumps(files, allow_nan=False)
        self.assertEqual(self.build(), self.build())

    def test_invalid_timing_and_media_are_rejected(self):
        cases = [
            {"duration": -1}, {"duration": float("nan")}, {"start": float("inf")},
            {"duration": 1e308}, {"duration": 1e-10}, {"source_start": -1},
            {"source_start": 19}, {"speed": 0}, {"speed": True},
            {"volume": -1}, {"path": "relative/video.mp4"},
            {"media_width": 10.5}, {"x": float("nan")},
            {"display_name": ""}, {"display_name": "x" * 121},
            {"display_name": "a\x7fb"}, {"display_name": "a\u0085b"},
            {"display_name": "a\u202eb"},
        ]
        for change in cases:
            with self.subTest(change=change):
                plan = example_plan()
                plan["clips"][0].update(change)
                with self.assertRaises(ValueError):
                    self.build(plan)

    def test_ambiguous_or_overlapping_tracks_are_rejected(self):
        for kind in ("overlap", "duplicate", "mixed", "metadata"):
            with self.subTest(kind=kind):
                plan = example_plan()
                if kind == "overlap":
                    plan["clips"][1]["start"] = 2
                elif kind == "duplicate":
                    plan["clips"][1]["id"] = plan["clips"][0]["id"]
                elif kind == "mixed":
                    plan["clips"][2]["track"] = "V1"
                else:
                    plan["clips"][1]["media_duration"] = 21
                with self.assertRaises(ValueError):
                    self.build(plan)

    def test_static_clip_speed_and_bad_text_style_are_rejected(self):
        for change in ({"speed": 2}, {"source_start": 1}, {"text": ""},
                       {"color": "red"}, {"font_size": 0}, {"y": 2},
                       {"display_name": "字幕名"}):
            with self.subTest(change=change):
                plan = example_plan()
                plan["clips"][-1].update(change)
                with self.assertRaises(ValueError):
                    self.build(plan)


if __name__ == "__main__":
    unittest.main()
