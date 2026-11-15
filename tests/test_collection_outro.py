"""Multi-folder planning and real chapter assembly with one physical camera outro."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from album_collection import load_project, scan_folders, select_part
from book_cache import cache_plan
from render_book import Book, ffmpeg_exe, render


class FolderPlanningTests(unittest.TestCase):
    def test_folders_keep_order_and_groups_can_cross_folder_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp)/"01", Path(temp)/"02"
            first.mkdir()
            second.mkdir()
            for folder, name in [(first, "街角_2.png"), (first, "街角_1.png"),
                                 (second, "街角_3.png"), (second, "雨后_1.png")]:
                Image.new("RGB", (10, 10), "gold").save(folder/name)
            plan = scan_folders([first, second])
            self.assertEqual(plan["image_count"], 4)
            self.assertEqual(plan["cross_folder_groups"], [1])
            self.assertEqual([item["original_name"] for item in plan["scenes"][0]["photos"]],
                             ["街角_1.png", "街角_2.png", "街角_3.png"])
            self.assertEqual([len(group["photos"]) for group in plan["scenes"]], [3, 1])

    def test_master_rejects_duplicate_ids_and_split_prefix_groups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, photo in [("a", "街角_1.png"), ("b", "街角_2.gif")]:
                (root/f"{name}.json").write_text(json.dumps({"scenes": [{"photo": photo, "elements": []}]}), encoding="utf-8")
            master = {"parts": [{"id": "one", "project": "a.json"}, {"id": "two", "project": "b.json"}]}
            path = root/"master.json"
            path.write_text(json.dumps(master), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "splits filename group"):
                load_project(path)
            master["allow_boundary_group_split"] = True
            path.write_text(json.dumps(master), encoding="utf-8")
            config, parts = load_project(path)
            self.assertEqual(len(config["scenes"]), 2)
            self.assertEqual(select_part(parts, "2")["id"], "two")
            self.assertTrue(Path(config["scenes"][1]["photo"]["file"]).is_absolute())
            master["parts"][1]["id"] = "one"
            path.write_text(json.dumps(master), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unique"):
                load_project(path)
            (root/"a.json").write_text(json.dumps({"title": "another book", "scenes": [{}]}), encoding="utf-8")
            master["parts"] = [master["parts"][0]]
            path.write_text(json.dumps(master), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "global settings"):
                load_project(path)


class ChapterExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.encoder = ffmpeg_exe()
            subprocess.run([cls.encoder, "-version"], check=True, capture_output=True)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            raise unittest.SkipTest(f"FFmpeg unavailable: {error}")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="album-chapters-")
        self.root = Path(self.temp.name)
        self.books = []
        self.cache = self.root/"cache"
        self.master = self.root/"master.json"
        for name in ["01-arrival", "02-walk"]:
            (self.root/name).mkdir()
        captions = ["抵达。", "沿着河岸。", "慢慢走。"]
        scenes = []
        for index, color in enumerate(["#d5b064", "#8c9f77", "#b47d66"]):
            folder = self.root/("01-arrival" if index == 0 else "02-walk")
            photo = f"photo-{index}.png"
            Image.new("RGB", (100, 140), color).save(folder/photo)
            if index == 2:
                photo = "motion.gif"
                first = Image.new("RGB", (100, 140), color)
                first.save(folder/photo, save_all=True, append_images=[Image.new("RGB", first.size, "#5379ac")],
                           duration=[250, 500], loop=0)
            sprite = Image.new("RGBA", (60, 80), (0, 0, 0, 0))
            ImageDraw.Draw(sprite).ellipse((5, 8, 52, 72), fill=color)
            sprite.save(folder/f"element-{index}.png")
            scenes.append({"photo": photo, "elements": [{"file": f"element-{index}.png"}],
                           "caption": captions[index], "narration": captions[index], "duration": 6})
        for name, pages, story in [("01-arrival", scenes[:1], {"entry": "抵达", "exit": "河岸"}),
                                   ("02-walk", scenes[1:], {"entry": "河岸", "exit": "告别"})]:
            (self.root/name/"chapter.json").write_text(json.dumps({"scenes": pages, "narrative": story}, ensure_ascii=False), encoding="utf-8")
        script = "".join(captions)
        self.config = {
            "parts": [{"id": "arrival", "project": "01-arrival/chapter.json"}, {"id": "walk", "project": "02-walk/chapter.json"}],
            "narrative": {"outline": ["抵达", "沿河散步", "收起回忆"]},
            "size": [480, 270], "fps": 4,
            "intro": {"mode": "cover-camera-book", "hero_hold": 1, "hero_transition": .2,
                      "photo_gap": .4, "photo_travel": .7, "merge_duration": .5, "photo_indices": [0, 2]},
            "outro": {"mode": "book-camera", "close_duration": .5, "photo_gap": .4,
                      "photo_travel": .7, "merge_duration": .5, "text_reveal": .25, "text_hold": .6, "fade_out": .25},
            "cover_recipe": {"A": "A2", "B": "B2", "C": "C5", "D": "D2", "seed": 4},
            "intake": {"title": {"mode": "none"}, "ending": {"mode": "user", "value": "下次见。"},
                       "copy": {"mode": "provided", "original": script, "corrected": script, "edits": []}},
            "caption_policy": "provided-script", "opening": .5, "page_turn": .5, "final_hold": .5,
            "theme": {"accent": "#a38b51", "cover": "#505744", "paper": "#fffaf0", "ink": "#302b25",
                      "background_gradient": {"colors": ["#d5cec1", "#bdc5c7"], "angle": 128}},
            "music": {"mode": "none"}, "sfx": True,
        }
        self.count = 0

    def tearDown(self):
        for book in self.books:
            for source in book._media_sources.values():
                if source.image is not None:
                    source.image.close()
        self.temp.cleanup()

    def book(self, config=None):
        self.master.write_text(json.dumps(config or self.config, ensure_ascii=False), encoding="utf-8")
        book = Book(self.master)
        self.books.append(book)
        return book

    def export(self, part=None, config=None):
        book = self.book(config)
        self.count += 1
        target = self.root/f"export-{self.count}.mp4"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            report = render(book, target, False, cache_dir=self.cache, part=part)
        return book, target, report

    def hashes(self, path):
        text = subprocess.run([self.encoder, "-v", "error", "-i", str(path), "-map", "0:v:0",
                               "-fps_mode", "passthrough", "-f", "framemd5", "-"],
                              check=True, text=True, capture_output=True).stdout
        return [line.rsplit(",", 1)[1].strip() for line in text.splitlines() if line and not line.startswith("#")]

    def test_outro_choices_motion_and_phase_order(self):
        book = self.book()
        outro = book.outro
        self.assertEqual(outro.rig.photo_indices, book.intro.photo_indices)
        self.assertTrue(outro.rig.card_sources[1].animated)
        self.assertLess(outro.close_duration, outro.text_start)
        self.assertLess(outro.text_start+outro.reveal, outro.duration)
        self.assertIsNotNone(outro.words.getbbox())
        end_page = book.segment_frame("ending", 2, book.final_hold)
        closing = outro.frame(0)
        self.assertLess(np.abs(np.asarray(end_page, dtype=float)-np.asarray(closing, dtype=float)).mean(), 1.5)
        elapsed = .3
        with patch.object(outro.rig, "card_at", wraps=outro.rig.card_at) as sample:
            outro.frame(outro.close_duration+elapsed)
        self.assertTrue(sample.call_args_list)
        self.assertTrue(all(abs(call.args[1]-elapsed) < 1e-8 for call in sample.call_args_list))
        with patch.object(book, "cover_at", wraps=book.cover_at) as cover_sample:
            outro.frame(outro.close_duration+.1)
            outro.frame(outro.close_duration+.2)
        clocks = [call.args[0] for call in cover_sample.call_args_list]
        self.assertTrue(clocks)
        self.assertEqual(clocks, sorted(clocks), "Animated cover time must move forward while the return path reverses")
        missing = copy.deepcopy(self.config)
        del missing["intake"]["ending"]
        with self.assertRaisesRegex(ValueError, "closing words"):
            self.book(missing)
        none = copy.deepcopy(self.config)
        none["intake"]["ending"] = {"mode": "none"}
        self.assertIsNone(self.book(none).outro.words.getbbox())

    def test_render_parts_then_master_only_adds_boundary_turn_and_preserves_content(self):
        _, first_target, first = self.export("arrival")
        _, second_target, second = self.export("walk")
        self.assertEqual(first["rendered_segments"], ["intro", "opening", "page-0001"])
        self.assertNotIn("intro", [job["id"] for job in second["segments"]])
        self.assertIn("outro", second["rendered_segments"])
        self.assertTrue(second["audio_reused"])
        book, target, final = self.export()
        self.assertEqual(final["rendered_segments"], ["turn-0001-0002"])
        self.assertEqual(sum(job["kind"] == "intro" for job in final["segments"]), 1)
        self.assertEqual(sum(job["kind"] == "outro" for job in final["segments"]), 1)
        self.assertEqual("".join(scene.text for scene in book.scenes), self.config["intake"]["copy"]["corrected"])
        self.assertEqual(book.parts[0]["narrative"]["exit"], book.parts[1]["narrative"]["entry"])
        self.assertEqual([scene.config["part_page"] for scene in book.scenes], [1, 1, 2])
        raw = self.hashes(target)
        self.assertEqual(raw, [frame for job in final["segments"] for frame in self.hashes(job["file"])])
        self.assertEqual(len(raw), round(book.total*book.fps))
        for part_report, part_target in [(first, first_target), (second, second_target)]:
            start = part_report["global_start_frame"]
            length = round(part_report["duration"]*book.fps)
            self.assertEqual(self.hashes(part_target), raw[start:start+length])
        part_timeline = json.loads(second_target.with_suffix(".timeline.json").read_text())
        self.assertEqual(part_timeline["intro"]["mode"], "none")
        self.assertEqual(part_timeline["scenes"][0]["start"], 0)
        changed = copy.deepcopy(self.config)
        changed["intake"]["ending"]["value"] = "再见啦。"
        _, revised, report = self.export(config=changed)
        self.assertEqual(report["rendered_segments"], ["outro"])
        self.assertTrue(report["audio_reused"])
        outro_start = next(job["start_frame"] for job in final["segments"] if job["id"] == "outro")
        self.assertEqual(self.hashes(revised)[:outro_start], raw[:outro_start])


if __name__ == "__main__":
    unittest.main()
