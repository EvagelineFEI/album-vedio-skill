"""Portable checks using temporary synthetic images; no movie is encoded."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw, features

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from album_inputs import filename_prefix, group_consecutive
from album_media import MediaSource
from book_cover import resolve_recipe
from render_book import Book


class GroupingTests(unittest.TestCase):
    def test_consecutive_groups_keep_order_and_every_photo(self):
        names = ["街角_01.jpg", "街角_02.gif", "IMG_0001.jpg", "IMG_0002.jpg",
                 "河边_01.jpg", "街角_03.jpg"]
        groups = group_consecutive(names)
        self.assertEqual([len(group["photos"]) for group in groups], [2, 1, 1, 1, 1])
        self.assertEqual([item["file"] for group in groups for item in group["photos"]], names)
        self.assertEqual([i for group in groups for i in group["source_indices"]], list(range(6)))

    def test_original_names_and_explicit_groups_survive_renaming(self):
        groups = group_consecutive([
            {"file": "cache-a.jpg", "original_name": "街角_01.jpg"},
            {"file": "cache-b.gif", "original_name": "街角_02.gif"},
            {"file": "IMG_0003.jpg", "group": "用户分组"},
            {"file": "other.png", "group": "用户分组"},
        ])
        self.assertEqual([len(group["photos"]) for group in groups], [2, 2])
        self.assertEqual(groups[0]["photos"][1]["original_name"], "街角_02.gif")
        self.assertEqual(filename_prefix("街角（2）.jpg"), filename_prefix("街角_01.jpg"))
        for name in ["IMG1234.jpg", "DSC_001.jpg", "2026-11-14.jpg"]:
            self.assertIsNone(filename_prefix(name))


class TemporaryMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="album-skill-test-")
        self.root = Path(self.temp.name)
        self.sources = []
        self.red = Image.new("RGBA", (40, 52), (0, 0, 0, 0))
        ImageDraw.Draw(self.red).rectangle((3, 5, 17, 22), fill="red")
        self.blue = Image.new("RGBA", (40, 52), (0, 0, 0, 0))
        ImageDraw.Draw(self.blue).rectangle((21, 12, 36, 33), fill="blue")
        self.red.save(self.root / "motion.gif", save_all=True, append_images=[self.blue],
                      duration=[100, 300], loop=1, disposal=2, transparency=0)
        self.red.save(self.root / "motion.png", save_all=True, append_images=[self.blue],
                      duration=[100, 300], loop=0, disposal=[0, 1], blend=[0, 0])

    def tearDown(self):
        for source in self.sources:
            if source.image is not None:
                source.image.close()
        self.red.close()
        self.blue.close()
        self.temp.cleanup()

    def source(self, filename, **options):
        source = MediaSource({"file": filename, **options}, lambda name: self.root / name, (100, 140))
        self.sources.append(source)
        return source

    def check_animation(self, source):
        self.assertTrue(source.animated)
        self.assertEqual(len(source.indices), 2)
        self.assertAlmostEqual(source.duration, .4, places=2)
        self.assertEqual(source.index_at(.05), 0)
        self.assertEqual(source.index_at(.15), 1)
        self.assertEqual(source.index_at(.45), 0)
        self.assertFalse(np.array_equal(source.frame(.05), source.frame(.15)))

    def test_gif_and_apng_preserve_frames_timing_and_alpha(self):
        for filename in ["motion.gif", "motion.png"]:
            with self.subTest(filename=filename):
                source = self.source(filename)
                self.check_animation(source)
                self.assertEqual(source.frame(.05).getchannel("A").getextrema(), (0, 255))

    def test_webp_keeps_real_motion(self):
        if not features.check("webp"):
            self.skipTest("Pillow has no WebP decoder")
        self.red.save(self.root / "motion.webp", save_all=True, append_images=[self.blue],
                      duration=[100, 300], loop=0, lossless=True)
        self.check_animation(self.source("motion.webp"))

    def test_playback_policies_and_start_offset(self):
        self.assertEqual(self.source("motion.gif", playback="source").index_at(.85), 1)
        self.assertEqual(self.source("motion.gif", playback="once").index_at(.45), 1)
        self.assertEqual(self.source("motion.gif", offset=.15).index_at(0), 1)

    def test_apng_poster_is_not_a_playable_frame(self):
        poster = Image.new("RGBA", self.red.size, "green")
        poster.save(self.root / "poster.png", save_all=True, default_image=True,
                    append_images=[self.red, self.blue], duration=[100, 300], loop=0)
        poster.close()
        source = self.source("poster.png")
        self.check_animation(source)
        frame = source.frame(.05)
        self.assertEqual(frame.getpixel((frame.width // 4, frame.height // 4)), (255, 0, 0, 255))

    def test_grouped_page_cover_print_and_cutout_all_keep_animation(self):
        Image.new("RGB", (100, 140), "#dac17b").save(self.root / "still.png")
        config = {
            "size": [640, 360], "fps": 30,
            "cover_recipe": {"A": "A2", "B": "B2", "C": "C5", "D": "D2", "seed": 4},
            "cover_photo_index": 1, "intro": {"mode": "cover-camera-book"},
            "intake": {"title": {"mode": "none"}, "copy": {
                "mode": "provided", "original": "今天天气真真好。", "corrected": "今天天气真好。",
                "edits": [{"before": "真真", "after": "真", "reason": "重复字"}]}},
            "caption_policy": "provided-script",
            "scenes": [{"group_key": "街角", "photos": ["still.png", "motion.gif"],
                        "elements": [{"file": "motion.png", "kind": "object"}],
                        "caption": "今天天气真好。", "narration": "今天天气真好。"}],
        }
        path = self.root / "project.json"
        path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        book = Book(path)
        self.sources.extend(book._media_sources.values())
        scene = book.scenes[0]
        self.assertEqual(len(book.scenes), 1)
        self.assertEqual(len(scene.photo_sources), 2)
        self.assertFalse(book.intro.has_title)
        self.assertEqual(book.config["title"], "")
        self.assertEqual(book.intro.title_reveal, 0)
        self.assertIsNone(book.cover_title.getbbox())
        for before, after in [
            (scene.left_at(.05), scene.left_at(.15)),
            (book.cover_at(.05), book.cover_at(.15)),
            (book.intro.card_at(1, .05), book.intro.card_at(1, .15)),
            (scene.sprite_at(0, .05), scene.sprite_at(0, .15)),
        ]:
            self.assertFalse(np.array_equal(before, after))
        self.assertEqual(book.frame(book.intro.merge_complete + .1).size, (640, 360))
        self.assertEqual(book.frame(scene.start + .15).size, (640, 360))
        timeline = book.timeline()
        self.assertEqual(timeline["intake"]["copy"]["corrected"], "今天天气真好。")
        self.assertEqual(len(timeline["scenes"][0]["photos"]), 2)
        self.assertTrue(timeline["scenes"][0]["photos"][1]["animated"])
        self.assertTrue(timeline["scenes"][0]["animated_elements"][0])
        # The five-photo limit applies to the camera intro, not to the book's page count.
        excessive = copy.deepcopy(config)
        excessive["intro"]["photo_count"] = 6
        path.write_text(json.dumps(excessive), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "1–5"):
            Book(path)


class CoverRecipeTests(unittest.TestCase):
    def test_same_project_is_repeatable_but_each_axis_can_vary(self):
        config = {"title": "Autumn Notes", "scenes": [{"photo": "street.jpg"}],
                  "cover_recipe": {"seed": 14}}
        self.assertEqual(resolve_recipe(config), resolve_recipe(copy.deepcopy(config)))
        recipes = [resolve_recipe({**config, "cover_recipe": {"seed": seed}}) for seed in range(40)]
        for axis in "ABCD":
            self.assertGreater(len({recipe[axis] for recipe in recipes}), 1)
        self.assertTrue(all(recipe["quiet_area_estimate"] >= .4 for recipe in recipes))


if __name__ == "__main__":
    unittest.main()
