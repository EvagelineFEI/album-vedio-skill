"""Close the same book, turn it into real prints and return them to the camera."""
import math

from PIL import Image, ImageDraw, ImageFont

from book_intro import CameraIntro, opacity, smooth
from book_design import contrast


class CameraOutro:
    def __init__(self, book):
        self.book = book
        self.config = book.config.get("outro", {})
        self.mode = self.config.get("mode", "none")
        self.duration, self.events = 0, []
        self.text = ""
        if self.mode == "none":
            return
        if self.mode != "book-camera":
            raise ValueError("outro.mode must be book-camera or none.")
        choice = book.config.get("intake", {}).get("ending", {})
        if choice.get("mode") not in {"user", "assistant", "none"}:
            raise ValueError("Ask whether the user wants closing words and record intake.ending.mode=user/assistant/none.")
        self.text = "" if choice["mode"] == "none" else str(choice.get("value", "")).strip()
        if choice["mode"] != "none" and not self.text:
            raise ValueError("The selected closing words must be written in intake.ending.value.")
        self.close_duration = float(self.config.get("close_duration", 1.3))
        self.reveal = float(self.config.get("text_reveal", .65)) if self.text else 0
        self.hold = float(self.config.get("text_hold", max(2.2, len(self.text)/6))) if self.text else float(self.config.get("text_hold", .8))
        self.fade = float(self.config.get("fade_out", .7))
        if not all(math.isfinite(value) for value in [self.close_duration, self.reveal, self.hold, self.fade]):
            raise ValueError("Outro timings must be finite.")
        if not .5 <= self.close_duration <= 5 or not 0 <= self.fade <= 3 or not 0 <= self.reveal <= 3 or self.hold < max(.4, len(self.text)/7):
            raise ValueError("Outro timings leave too little time to close the book or read the closing words.")
        rig_config = {"mode": "camera-stack", "photo_gap": .55, "photo_travel": 1.05, "merge_duration": .9}
        for key in ["photo_indices", "photo_count", "photo_gap", "photo_travel", "merge_duration", "camera_asset"]:
            if key in self.config:
                rig_config[key] = self.config[key]
        if "photo_indices" not in rig_config and "photo_count" not in rig_config and hasattr(book.intro, "photo_indices"):
            rig_config["photo_indices"] = book.intro.photo_indices
        if "camera_asset" not in rig_config and book.config.get("intro", {}).get("camera_asset"):
            rig_config["camera_asset"] = book.config["intro"]["camera_asset"]
        self.rig = CameraIntro(book, book.photo_items, config=rig_config, show_title=False)
        self.return_duration = self.rig.merge_complete
        self.text_start = self.close_duration+self.return_duration
        self.events = [self.close_duration+self.return_duration-shot for shot in reversed(self.rig.shots)]
        self.duration = self.text_start+self.reveal+self.hold+self.fade
        self.words = self.make_words()

    def make_words(self):
        b = self.book
        layer = Image.new("RGBA", (b.w, b.h))
        if not self.text:
            return layer
        width, height = b.w*.46, b.h*.56
        size = max(12, round(b.h*.072))
        while size >= 12:
            font = ImageFont.truetype(str(b.font_file), size)
            lines = []
            for paragraph in self.text.split("\n"):
                line = ""
                for char in paragraph:
                    if line and font.getlength(line+char) > width:
                        lines.append(line)
                        line = ""
                    line += char
                lines.append(line)
            if len(lines)*size*1.5 <= height:
                break
            size -= 1
        if size < 12:
            raise ValueError("Closing words are too long for the camera outro; shorten them or use another text treatment.")
        sample = b.background.convert("RGB").getpixel((round(b.w*.68), round(b.h*.48)))
        backdrop = "#%02x%02x%02x" % sample
        ink = max([b.theme.get("ink", "#302b25"), "#fffaf0", "#242421"], key=lambda value: contrast(value, backdrop))
        draw = ImageDraw.Draw(layer)
        y = b.h*.48-len(lines)*size*1.5/2
        for line in lines:
            draw.text((b.w*.68, y), line, font=font, fill=ink, anchor="mt")
            y += size*1.5
        return layer

    def frame(self, time):
        b = self.book
        if time < self.close_duration:
            progress = smooth(time/self.close_duration)
            scene = b.scenes[-1]
            stage = Image.blend(scene.stage, b.closed_stage, progress)
            frame = b.put_pages(None, scene.right(scene.duration), closed=True, stage=stage)
            cover = b.cover_at(time, with_title=False)
            cover.alpha_composite(opacity(b.cover_title, 1-smooth((progress-.65)/.35)))
            left = scene.left_at(scene.incoming+scene.duration+b.final_hold+time)
            return b.turn_sheet(frame, cover, left, 1-progress)
        elapsed = time-self.close_duration
        reverse = max(0, self.return_duration-elapsed)
        frame = self.rig._camera_frame(reverse, media_time=elapsed, cover_time=time)
        if self.text and time >= self.text_start:
            frame.alpha_composite(opacity(self.words, smooth((time-self.text_start)/max(.001, self.reveal))))
        if self.fade and time > self.duration-self.fade:
            frame = Image.blend(frame, b.background, smooth((time-self.duration+self.fade)/self.fade))
        return frame

    def timeline(self):
        if self.mode == "none":
            return {"mode": "none", "duration": 0, "events": []}
        return {"mode": self.mode, "duration": self.duration, "close_complete": self.close_duration,
                "return_complete": self.text_start, "text_start": self.text_start,
                "text_complete": self.text_start+self.reveal, "text": self.text,
                "photo_indices": self.rig.photo_indices, "events": self.events,
                "animated_photos": [source.animated for source in self.rig.card_sources]}
