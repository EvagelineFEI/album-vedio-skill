"""Exercise real encoding and reuse with tiny temporary fixtures, never personal media."""
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
import wave

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from book_cache import cache_plan, file_digest, parse_pages
from render_book import Book, ffmpeg_exe, render


class IncrementalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.encoder = ffmpeg_exe()
            subprocess.run([cls.encoder, "-version"], check=True, capture_output=True)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            raise unittest.SkipTest(f"FFmpeg unavailable: {error}")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="album's test ")
        self.root = Path(self.temp.name)
        self.books = []
        for index, color in enumerate(["#c8aa67", "#8a9480", "#aa906b"]):
            Image.new("RGB", (100, 140), color).save(self.root/f"photo-{index}.png")
            element = Image.new("RGBA", (60, 80), (0, 0, 0, 0))
            ImageDraw.Draw(element).ellipse((5, 8, 52, 72), fill=color)
            element.save(self.root/f"element-{index}.png")
        red = Image.new("RGB", (100, 140), "#c66e57")
        blue = Image.new("RGB", red.size, "#5379ac")
        red.save(self.root/"motion.gif", save_all=True, append_images=[blue], duration=[250, 500], loop=0)
        self.base = {
            "size": [480, 270], "fps": 4, "intro": {"mode": "cover"},
            "cover_recipe": {"A": "A2", "B": "B2", "C": "C5", "D": "D2", "seed": 4},
            "intake": {"title": {"mode": "none"}}, "caption_policy": "provided-script",
            "opening": .45, "page_turn": .45, "final_hold": .45,
            "theme": {"accent": "#a38b51", "cover": "#505744", "paper": "#fffaf0", "ink": "#302b25",
                      "background_gradient": {"colors": ["#d5cec1", "#bdc5c7"], "angle": 128}},
            "music": {"mode": "none"}, "sfx": True,
            "scenes": [{"photo": "motion.gif" if i == 2 else f"photo-{i}.png",
                        "elements": [{"file": f"element-{i}.png"}], "caption": "初秋。",
                        "duration": 6, "layout": "caption-top"} for i in range(3)],
        }
        self.cache = self.root/"cache with 'quotes'"
        self.project = self.root/"project.json"
        self.sequence = 0

    def tearDown(self):
        for book in self.books:
            for source in book._media_sources.values():
                if source.image is not None:
                    source.image.close()
        self.temp.cleanup()

    def book(self, config=None):
        self.project.write_text(json.dumps(config or self.base, ensure_ascii=False), encoding="utf-8")
        book = Book(self.project)
        self.books.append(book)
        return book

    def export(self, config=None, **options):
        book = self.book(config)
        self.sequence += 1
        target = self.root/f"result-{self.sequence}.mp4"
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            report = render(book, target, False, cache_dir=self.cache, **options)
        return book, target, report

    def hashes(self, path):
        data = subprocess.run([self.encoder, "-v", "error", "-i", str(path), "-map", "0:v:0",
                               "-fps_mode", "passthrough", "-f", "framemd5", "-"],
                              capture_output=True, text=True, check=True).stdout
        return [line.rsplit(",", 1)[1].strip() for line in data.splitlines() if line and not line.startswith("#")]

    def test_planning_dependencies_and_frame_alignment_without_writes(self):
        config = copy.deepcopy(self.base)
        config["intro"]["mode"] = "cover-camera-book"
        original = cache_plan(self.book(config), self.encoder, self.cache)
        self.assertFalse(self.cache.exists())
        config["scenes"][1]["caption"] = "晚风。"
        edited = cache_plan(self.book(config), self.encoder, self.cache)
        before = {job.id: job.key for job in original.segments}
        changed = {job.id for job in edited.segments if job.key != before[job.id]}
        self.assertEqual(changed, {"page-0002", "turn-0001-0002", "turn-0002-0003"})
        self.assertEqual(original.audio_key, edited.audio_key)
        self.assertFalse(self.cache.exists())
        cli = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]/"scripts/render_book.py"),
                              str(self.project), "--cache-plan", "--cache-dir", str(self.cache)],
                             check=True, text=True, capture_output=True)
        self.assertEqual(len(json.loads(cli.stdout)["segments"]), 8)
        self.assertFalse(self.cache.exists())
        book = self.book()
        self.assertEqual(book.opening, .5)
        self.assertEqual(book.turn, .5)
        self.assertEqual(book.total*book.fps, round(book.total*book.fps))
        self.assertEqual(parse_pages("2, 3,2", 3), {2, 3})
        for text in ["0", "4", "2,a"]:
            with self.assertRaises(ValueError):
                parse_pages(text, 3)

    def test_real_exports_reuse_unaffected_video_and_keep_audio_and_animation_aligned(self):
        first, target, baseline = self.export()
        self.assertFalse(baseline["audio_reused"])
        self.assertEqual(len(baseline["rendered_segments"]), 7)
        base_hashes = self.hashes(target)
        combined = [frame for job in baseline["segments"] for frame in self.hashes(job["file"])]
        self.assertEqual(base_hashes, combined, "Final assembly must preserve every cached video frame")
        self.assertEqual(len(base_hashes), round(first.total*first.fps))
        original_files = {job["id"]: (Path(job["file"]), file_digest(job["file"]), Path(job["file"]).stat().st_mtime_ns)
                          for job in baseline["segments"]}
        with patch("book_cache.encode_segment", side_effect=AssertionError("Unchanged video was re-encoded")), \
             patch("book_cache.encode_audio", side_effect=AssertionError("Unchanged audio was remixed")):
            _, same_target, same = self.export()
        self.assertEqual(same["rendered_segments"], [])
        self.assertTrue(same["audio_reused"])
        self.assertEqual(self.hashes(same_target), base_hashes)
        for path, value, stamp in original_files.values():
            self.assertEqual((file_digest(path), path.stat().st_mtime_ns), (value, stamp))

        revised = copy.deepcopy(self.base)
        revised["scenes"][1]["layout"] = "caption-left"
        _, edited_target, edited = self.export(revised)
        affected = {"page-0002", "turn-0001-0002", "turn-0002-0003"}
        self.assertEqual(set(edited["rendered_segments"]), affected)
        self.assertTrue(edited["audio_reused"])
        changed_hashes = self.hashes(edited_target)
        for job in baseline["segments"]:
            if job["id"] not in affected:
                start, count = job["start_frame"], job["frames"]
                self.assertEqual(changed_hashes[start:start+count], base_hashes[start:start+count])
        self.assertNotEqual(changed_hashes, base_hashes)

        # File contents, rather than filenames or modification times, invalidate a cutout.
        element_path = self.root/"element-1.png"
        original_element = element_path.read_bytes()
        element = Image.new("RGBA", (60, 80), (0, 0, 0, 0))
        ImageDraw.Draw(element).ellipse((5, 8, 52, 72), fill="#ce4646")
        element.save(element_path)
        _, _, asset_edit = self.export()
        self.assertEqual(set(asset_edit["rendered_segments"]), affected)
        element_path.write_bytes(original_element)

        # A non-integral requested duration is aligned to the frame grid; page 3 stays reusable.
        longer = copy.deepcopy(self.base)
        longer["scenes"][1]["duration"] = 6.1
        book, longer_target, length_edit = self.export(longer)
        self.assertEqual(book.scenes[1].duration, 6.25)
        self.assertEqual(set(length_edit["rendered_segments"]), affected)
        self.assertFalse(length_edit["audio_reused"])
        self.assertEqual(len(self.hashes(longer_target)), round(book.total*book.fps))
        downstream = next(job for job in length_edit["segments"] if job["id"] == "page-0003")
        original_downstream = next(job for job in baseline["segments"] if job["id"] == "page-0003")
        self.assertEqual(downstream["key"], original_downstream["key"])
        later = self.hashes(longer_target)
        self.assertEqual(later[downstream["start_frame"]:downstream["start_frame"]+downstream["frames"]],
                         base_hashes[original_downstream["start_frame"]:original_downstream["start_frame"]+original_downstream["frames"]])

        voice = (np.sin(np.arange(44100)/44100*2*np.pi*440)*.1*32767).astype("<i2")
        with wave.open(str(self.root/"speech.wav"), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(44100)
            wav.writeframes(voice.tobytes())
        spoken = copy.deepcopy(self.base)
        spoken["scenes"][1]["voiceover"] = "speech.wav"
        _, spoken_target, voice_edit = self.export(spoken)
        self.assertEqual(voice_edit["rendered_segments"], [])
        self.assertFalse(voice_edit["audio_reused"])
        self.assertEqual(self.hashes(spoken_target), base_hashes)
        self.assertNotEqual(file_digest(spoken_target.with_suffix(".audio.wav")), file_digest(target.with_suffix(".audio.wav")))

        global_edit = copy.deepcopy(self.base)
        global_edit["theme"]["paper"] = "#fff2ce"
        all_changed = cache_plan(self.book(global_edit), self.encoder, self.cache)
        self.assertEqual(len(all_changed.report()["rendered_segments"]), 7)

        _, _, forced = self.export(rebuild_pages={2})
        self.assertEqual(set(forced["rendered_segments"]), affected)
        self.assertTrue(forced["audio_reused"])

        # A damaged chunk cannot masquerade as a cache hit; only that chunk needs repair.
        broken = original_files["page-0003"][0]
        broken.write_bytes(b"damaged cached movie")
        _, fixed_target, repaired = self.export()
        self.assertEqual(repaired["rendered_segments"], ["page-0003"])
        self.assertEqual(self.hashes(fixed_target), base_hashes)
        self.assertTrue(fixed_target.with_suffix(".render.json").is_file())


if __name__ == "__main__":
    unittest.main()
