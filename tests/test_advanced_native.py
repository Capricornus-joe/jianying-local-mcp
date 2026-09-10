"""Schema-level advanced-property tests, independent of installed Jianying."""

from copy import deepcopy
import json
import unittest

from jianying_local_mcp.advanced_native import apply_advanced


class AdvancedNativeTests(unittest.TestCase):
    def setUp(self):
        self.clip = {"id": "test", "kind": "video", "duration": 4, "has_audio": True}
        self.segment = {"clip": {"alpha": 1, "flip": {"horizontal": False, "vertical": False},
                                 "rotation": 0, "scale": {"x": 1, "y": 1}, "transform": {"x": 0, "y": 0}},
                        "common_keyframes": [], "extra_material_refs": ["speed"],
                        "uniform_scale": {"on": True, "value": 1}}
        self.material = {"id": "media", "type": "video", "width": 1920, "height": 1080}
        self.materials = {"videos": [self.material], "audio_fades": []}

    def apply(self):
        apply_advanced(self.clip, self.segment, self.material, self.materials, lambda value: value)

    def test_keyframes_are_sorted_clip_relative_linear_and_nonuniform(self):
        self.clip["source_start"] = 15
        self.clip["speed"] = 2
        self.clip["keyframes"] = {
            "x": [{"time": 4, "value": 0.4}, {"time": 0, "value": -0.4}],
            "scale_x": [{"time": 0, "value": 1}, {"time": 4, "value": 1.4}],
            "scale_y": [{"time": 0, "value": 1}, {"time": 4, "value": 1.4}],
            "opacity": [{"time": 0, "value": 0}, {"time": 0.5, "value": 1}],
        }
        self.apply()
        lists = self.segment["common_keyframes"]
        self.assertEqual(lists[0]["property_type"], "KFTypePositionX")
        self.assertEqual([point["time_offset"] for point in lists[0]["keyframe_list"]], [0, 4_000_000])
        self.assertEqual(lists[0]["keyframe_list"][0]["values"], [-0.4])
        self.assertEqual(lists[0]["keyframe_list"][0]["curveType"], "Line")
        self.assertFalse(self.segment["uniform_scale"]["on"])
        self.assertEqual(len({point["id"] for group in lists for point in group["keyframe_list"]}), 8)
        first = deepcopy(self.segment)
        self.apply()
        self.assertEqual(self.segment, first)

    def test_audio_fades_are_registered_and_reference_resolves(self):
        self.clip["kind"] = "audio"
        self.segment["clip"] = None
        self.clip["audio_fade"] = {"in": 0.25, "out": 0.75}
        self.apply()
        fade = self.materials["audio_fades"][0]
        self.assertEqual(fade["fade_in_duration"], 250_000)
        self.assertEqual(fade["fade_out_duration"], 750_000)
        self.assertEqual(fade["type"], "audio_fade")
        self.assertIn(fade["id"], self.segment["extra_material_refs"])
        self.apply()
        self.assertEqual(len(self.materials["audio_fades"]), 1)
        self.assertEqual(self.segment["extra_material_refs"].count(fade["id"]), 1)

    def test_transform_and_crop_do_not_alter_timing(self):
        self.segment["target_timerange"] = {"start": 2_000_000, "duration": 4_000_000}
        self.clip["transform"] = {"scale_x": 1.2, "scale_y": 0.9, "x": -0.3, "y": 0.4,
                                  "rotation": 15, "opacity": 0.8, "flip_horizontal": True,
                                  "flip_vertical": False}
        self.clip["crop"] = {"left": 0.1, "top": 0.2, "right": 0.8, "bottom": 0.9}
        self.apply()
        self.assertEqual(self.segment["clip"]["scale"], {"x": 1.2, "y": 0.9})
        self.assertTrue(self.segment["clip"]["flip"]["horizontal"])
        self.assertEqual(self.segment["clip"]["alpha"], 0.8)
        self.assertEqual(self.material["crop"]["lower_right_x"], 0.8)
        self.assertEqual(self.material["crop"]["upper_left_y"], 0.2)
        self.assertEqual(self.segment["target_timerange"], {"start": 2_000_000, "duration": 4_000_000})

    def text_fixture(self):
        self.clip["kind"] = "text"
        self.material.update(type="text", check_flag=7,
                             content=json.dumps({"text": "标题", "styles": [{"range": [0, 2], "size": 8}]}))

    def test_text_styles_preserve_text_and_add_outline_background_shadow(self):
        self.text_fixture()
        self.clip["text_style"] = {
            "bold": True, "italic": True, "underline": True, "alignment": "center",
            "stroke_color": "#FF8000", "stroke_width": 40,
            "background_color": "#123456", "background_opacity": 0.5, "background_radius": 0.3,
            "shadow_color": "#000000", "shadow_opacity": 0.8, "shadow_diffuse": 30,
            "shadow_distance": 6, "shadow_angle": -30, "letter_spacing": 2, "line_spacing": 1,
        }
        self.apply()
        content = json.loads(self.material["content"])
        style = content["styles"][0]
        self.assertEqual(content["text"], "标题")
        self.assertTrue(style["bold"] and style["italic"] and style["underline"])
        self.assertEqual(style["size"], 8)
        self.assertAlmostEqual(style["strokes"][0]["width"], 0.08)
        self.assertAlmostEqual(style["shadows"][0]["diffuse"], 0.05)
        self.assertEqual(self.material["background_color"], "#123456")
        self.assertEqual(self.material["background_alpha"], 0.5)
        self.assertEqual(self.material["check_flag"], 7 | 8 | 16 | 32)
        self.assertEqual(self.material["letter_spacing"], 0.1)
        self.assertAlmostEqual(self.material["line_spacing"], 0.07)

    def test_bad_advanced_input_is_atomic(self):
        invalid = [
            {"transform": {"opacity": 2}}, {"transform": {"flip_horizontal": "yes"}},
            {"transform": {"unknown": 1}}, {"crop": {"left": 0.8, "top": 0, "right": 0.2, "bottom": 1}},
            {"keyframes": {"x": [{"time": 5, "value": 1}]}},
            {"keyframes": {"x": [{"time": 0, "value": 0}, {"time": 0, "value": 1}]}},
            {"keyframes": {"x": [{"time": 0, "value": float("nan")}]}},
            {"keyframes": {"volume": [{"time": 0, "value": 1}]}},
            {"audio_fade": {"in": 3, "out": 2}},
            {"transform": {"x": 0.5}, "audio_fade": {"in": -1}},
        ]
        for settings in invalid:
            with self.subTest(settings=settings):
                self.clip = {"id": "test", "kind": "video", "duration": 4, "has_audio": True, **settings}
                before = deepcopy((self.segment, self.material, self.materials))
                with self.assertRaises(ValueError):
                    self.apply()
                self.assertEqual((self.segment, self.material, self.materials), before)

    def test_type_mismatches_and_bad_text_are_rejected(self):
        self.clip.update(kind="audio", transform={"x": 0.2})
        with self.assertRaises(ValueError):
            self.apply()
        self.clip = {"id": "test", "kind": "text", "duration": 4,
                     "text_style": {"stroke_color": "red"}}
        self.text_fixture()
        with self.assertRaises(ValueError):
            self.apply()
        self.clip = {"id": "test", "kind": "video", "duration": 4, "has_audio": False,
                     "audio_fade": {"in": 1}}
        with self.assertRaises(ValueError):
            self.apply()

    def test_circle_mask_uses_modern_array_and_correct_aspect_ratio(self):
        self.clip["mask"] = {"shape": "circle", "height": 0.5, "x": 0.1, "y": -0.2,
                             "feather": 20, "rotation": 15, "invert": False}
        self.apply()
        mask = self.materials["common_mask"][0]
        self.assertNotIn("masks", self.materials)
        self.assertNotIn("common_masks", self.materials)
        self.assertTrue(self.segment["enable_video_mask"])
        self.assertEqual(mask["resource_id"], "6791700663249146381")
        self.assertEqual(mask["resource_type"], "circle")
        self.assertAlmostEqual(mask["config"]["width"], 0.28125)
        self.assertEqual(mask["config"]["height"], 0.5)
        self.assertEqual(mask["config"]["feather"], 0.2)
        self.assertIn(mask["id"], self.segment["extra_material_refs"])
        self.apply()
        self.assertEqual(len(self.materials["common_mask"]), 1)

    def test_rectangle_and_linear_mask_resource_shapes(self):
        self.clip["mask"] = {"shape": "rectangle", "width": 0.8, "height": 0.4, "round_corner": 25}
        self.apply()
        mask = self.materials["common_mask"][0]
        self.assertEqual(mask["resource_type"], "rectangle")
        self.assertEqual(mask["config"]["roundCorner"], 0.25)
        self.clip["mask"] = {"shape": "linear", "rotation": 90, "invert": True}
        self.apply()
        self.assertEqual(self.materials["common_mask"][0]["resource_type"], "line")

    def test_resolved_animations_and_transition_get_timing_and_refs(self):
        resource = {"name": "synthetic entrance", "effect_id": "effect-in", "resource_id": "resource-in",
                    "path": "/example/cache/animation", "cached": True, "kind": "video_animation",
                    "animation_type": "in", "free_status": "free_in_catalog", "metadata_verified": True}
        outro = {**resource, "name": "synthetic exit", "effect_id": "effect-out",
                 "resource_id": "resource-out", "animation_type": "out"}
        self.clip["animations"] = [{"type": "in", "duration": 0.5, "resource": resource},
                                   {"type": "out", "duration": 0.75, "resource": outro}]
        self.clip["transition_out"] = {"duration": 0.4, "resource": {
            "kind": "transition", "name": "synthetic transition", "effect_id": "trans-effect",
            "resource_id": "trans-resource", "path": "/example/cache/transition", "is_overlap": True}}
        self.apply()
        container = self.materials["material_animations"][0]
        self.assertEqual(container["type"], "sticker_animation")
        first, last = container["animations"]
        self.assertEqual(first["start"], 0)
        self.assertEqual(last["start"], 3_250_000)
        self.assertEqual(last["duration"], 750_000)
        self.assertEqual(first["path"], "/example/cache/animation")
        self.assertEqual(first["category_id"], "")
        transition = self.materials["transitions"][0]
        self.assertEqual(transition["duration"], 400_000)
        self.assertTrue(transition["is_overlap"])
        for record in (container, transition):
            self.assertIn(record["id"], self.segment["extra_material_refs"])
        self.apply()
        self.assertEqual(len(self.materials["material_animations"]), 1)
        self.assertEqual(len(self.materials["transitions"]), 1)

    def test_bad_mask_and_resource_requests_fail_without_partial_mutation(self):
        invalid = [
            {"mask": {"shape": "unknown"}}, {"mask": {"shape": "circle", "round_corner": 5}},
            {"mask": {"shape": "rectangle", "width": 0}},
            {"mask": {"shape": "linear", "invert": "yes"}},
            {"animations": [{"type": "in", "duration": 0.5, "resource": {"name": "missing ids"}}]},
            {"animations": [{"type": "in", "duration": 0.5, "resource": {
                "name": "remote", "effect_id": "e", "resource_id": "r", "path": "https://example.com/cache"}}]},
            {"animations": [{"type": "in", "duration": 0.5, "resource": {
                "name": "unready", "effect_id": "e", "resource_id": "r", "cached": True,
                "ready_to_reference": False}}]},
            {"transition_out": {"duration": 0.4, "resource": {
                "name": "unknown overlap", "effect_id": "e", "resource_id": "r"}}},
        ]
        for request in invalid:
            with self.subTest(request=request):
                self.clip = {"id": "test", "kind": "video", "duration": 4,
                             "transform": {"x": 0.3}, **request}
                before = deepcopy((self.segment, self.material, self.materials))
                with self.assertRaises(ValueError):
                    self.apply()
                self.assertEqual((self.segment, self.material, self.materials), before)


if __name__ == "__main__":
    unittest.main()
