"""Camera prints the actual project photos, which gather into an untitled book."""
import math

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from book_design import ASSETS


def smooth(value):
    value = max(0, min(1, value))
    return value*value*(3-2*value)


def opacity(image, amount):
    if amount >= .999:
        return image
    out = image.copy()
    out.putalpha(image.getchannel("A").point(lambda p: round(p*max(0, amount))))
    return out


def centered(canvas, tile, center):
    canvas.alpha_composite(tile, (round(center[0]-tile.width/2), round(center[1]-tile.height/2)))


class CameraIntro:
    def __init__(self, book, photo_paths, config=None, show_title=True):
        self.book = book
        self.config = book.config.get("intro", {}) if config is None else config
        self.show_title = show_title
        # Unversioned existing manifests retain their cover-only opening.
        self.mode = self.config.get("mode", "cover")
        if self.mode not in {"cover", "camera-stack", "cover-camera-book"}:
            raise ValueError("intro.mode must be cover, camera-stack or cover-camera-book.")
        self.duration, self.shots = 0, []
        if self.mode == "cover":
            return
        self.has_title = show_title and bool(str(book.config.get("title", "")).strip())
        if show_title and not self.has_title and book.config.get("intake", {}).get("title", {}).get("mode") != "none":
            raise ValueError("Choose an album title or record intake.title.mode=none after asking the user.")
        indices = self.config.get("photo_indices")
        if indices is None:
            count = int(self.config.get("photo_count", min(5, len(photo_paths))))
            if not 1 <= count <= min(5, len(photo_paths)):
                raise ValueError("Camera printing is limited to 1–5 available project photos.")
            indices = [round(i*(len(photo_paths)-1)/max(1, count-1)) for i in range(count)]
        if not 1 <= len(indices) <= 5 or len(set(indices)) != len(indices) or any(not isinstance(i, int) or i < 0 or i >= len(photo_paths) for i in indices):
            raise ValueError("intro.photo_indices must contain 1–5 unique valid zero-based photo indices.")
        self.photo_indices = indices
        count = len(indices)
        self.hero_hold = float(self.config.get("hero_hold", 2.2)) if self.mode == "cover-camera-book" else 0
        self.hero_transition = float(self.config.get("hero_transition", .65)) if self.mode == "cover-camera-book" else 0
        if self.mode == "cover-camera-book" and (not 1 <= self.hero_hold <= 6 or not .2 <= self.hero_transition <= 2):
            raise ValueError("Hero cover hold must be 1–6s; transition must be .2–2s.")
        self.camera_offset = self.hero_hold+self.hero_transition
        self.gap = float(self.config.get("photo_gap", .80))
        self.travel = float(self.config.get("photo_travel", 1.2))
        self.merge_duration = float(self.config.get("merge_duration", 1.15))
        self.title_delay = float(self.config.get("title_delay", .25)) if self.has_title else 0
        self.title_reveal = float(self.config.get("title_reveal", .90)) if self.has_title else 0
        self.title_hold = float(self.config.get("title_hold", .70)) if self.has_title else .35
        if not .4 <= self.gap <= 3 or not .7 <= self.travel <= 3 or not .5 <= self.merge_duration <= 3:
            raise ValueError("Camera printing/merging timing is outside its supported range.")
        if self.has_title and (not 0 <= self.title_delay <= 3 or not .2 <= self.title_reveal <= 3 or not .2 <= self.title_hold <= 3):
            raise ValueError("Invalid title timing.")
        self.shots = [self.camera_offset+.30+i*self.gap for i in range(count)]
        self.stack_complete = self.shots[-1]+self.travel
        self.merge_start = self.stack_complete+.30
        self.merge_complete = self.merge_start+self.merge_duration
        self.title_start = self.merge_complete+self.title_delay
        self.title_complete = self.title_start+self.title_reveal
        self.duration = self.title_complete+self.title_hold
        camera_path = book.asset(self.config["camera_asset"]) if self.config.get("camera_asset") else ASSETS/"instant-camera.png"
        with Image.open(camera_path) as image:
            camera = image.convert("RGBA")
            if camera.getchannel("A").getextrema()[0] > 240:
                raise ValueError("Camera intro asset must have a transparent background.")
            bbox = camera.getchannel("A").getbbox()
            if not bbox:
                raise ValueError("Camera intro asset is empty.")
            camera = camera.crop(bbox)
        self.camera = ImageOps.contain(camera, (round(book.w*.31), round(book.h*.49)), Image.Resampling.LANCZOS)
        self.camera_center = (book.w*.22, book.h*.44)
        self.cards, self.card_sources, self.card_cache = [], [], {}
        self.card_w, self.card_h = round(book.w*.16), round(book.h*.36)
        for item in [photo_paths[i] for i in self.photo_indices]:
            self.card_sources.append(book.media(item, (round(self.card_w*.91), round(self.card_h*.84))))
        self.cards = [self.card_at(i, 0) for i in range(len(self.card_sources))]

    def card_at(self, index, time):
        source = self.card_sources[index]
        key = (index, source.index_at(time))
        if key not in self.card_cache:
            card = Image.new("RGBA", (self.card_w, self.card_h), "#fffdf6")
            centered(card, source.frame(time), (card.width/2, card.height*.455))
            self.card_cache[key] = card
            if len(self.card_cache) > 20:
                self.card_cache.pop(next(iter(self.card_cache)))
        return self.card_cache[key]

    def blank_book(self, title_opacity=0, time=0):
        b = self.book
        out = b.closed_stage.copy()
        cover = b.cover_at(time, with_title=self.show_title and not self.has_title)
        if title_opacity > 0:
            cover.alpha_composite(opacity(b.cover_title, title_opacity))
        out.alpha_composite(cover, (b.cx, b.top))
        return out

    def draw_card(self, frame, card, center, angle, size=None, alpha=1):
        if size:
            card = card.resize((max(2, round(size[0])), max(2, round(size[1]))), Image.Resampling.BICUBIC)
        tile = card.rotate(angle, Image.Resampling.BICUBIC, expand=True)
        pad = max(3, round(self.book.w*.010))
        plate = Image.new("RGBA", (tile.width+pad*4, tile.height+pad*4))
        shadow = Image.new("RGBA", plate.size, "#3c3025")
        mask = Image.new("L", plate.size)
        mask.paste(tile.getchannel("A"), (2*pad+pad//2, 2*pad+pad))
        shadow.putalpha(mask.filter(ImageFilter.GaussianBlur(pad*.7)).point(lambda p: round(p*.20)))
        plate.alpha_composite(shadow)
        centered(plate, tile, (plate.width/2, plate.height/2))
        centered(frame, opacity(plate, alpha), center)

    def frame(self, time):
        if self.mode == "cover-camera-book":
            if time < self.hero_hold:
                return self.book.hero_cover_frame(time)
            if time < self.camera_offset:
                progress = smooth((time-self.hero_hold)/self.hero_transition)
                return Image.blend(self.book.hero_cover_frame(self.hero_hold), self._camera_frame(time), progress)
        return self._camera_frame(time)

    def _camera_frame(self, time, media_time=None, cover_time=None):
        b = self.book
        cover_clock = max(0, time-self.merge_start) if cover_time is None else cover_time
        if time >= self.merge_complete:
            p = smooth((time-self.title_start)/self.title_reveal) if self.has_title else 0
            return self.blank_book(p, cover_clock)
        frame = b.background.copy()
        front_prints = Image.new("RGBA", frame.size)
        merge = smooth((time-self.merge_start)/self.merge_duration)
        target = (b.cx+b.pw/2, b.top+b.ph/2)
        stack = (b.w*.70, b.h*.52)
        for i, (shot, card) in enumerate(zip(self.shots, self.cards)):
            elapsed = time-shot
            if elapsed < 0:
                continue
            card = self.card_at(i, elapsed if media_time is None else media_time)
            travel = min(1, elapsed/self.travel)
            end_angle = [-7, 5, -3, 8, -5, 3][i]
            offset = ((i-(len(self.cards)-1)/2)*b.w*.006, (i-(len(self.cards)-1)/2)*b.h*.007)
            if travel < 1:
                # First eject below the physical print slot, then arc toward the stack.
                slot = (self.camera_center[0], self.camera_center[1]+self.camera.height*.36)
                if travel < .24:
                    p = smooth(travel/.24)
                    center = (slot[0]+b.w*.012*p, slot[1]+self.card_h*(-.38+.88*p))
                    angle = -4*p
                else:
                    p = smooth((travel-.24)/.76)
                    a = (slot[0]+b.w*.012, slot[1]+self.card_h*.50)
                    control = (b.w*.45, b.h*.91)
                    end = (stack[0]+offset[0], stack[1]+offset[1])
                    center = ((1-p)**2*a[0]+2*(1-p)*p*control[0]+p*p*end[0],
                              (1-p)**2*a[1]+2*(1-p)*p*control[1]+p*p*end[1])
                    angle = -4*(1-p)+end_angle*p
                size = None
            else:
                center = (stack[0]*(1-merge)+target[0]*merge+offset[0]*(1-merge),
                          stack[1]*(1-merge)+target[1]*merge+offset[1]*(1-merge))
                angle = end_angle*(1-merge)
                size = (self.card_w*(1-merge)+b.pw*merge, self.card_h*(1-merge)+b.ph*merge)
            self.draw_card(frame, card, center, angle, size=size)
            if travel < .24:
                emerging = Image.new("RGBA", frame.size)
                self.draw_card(emerging, card, center, angle, size=size)
                visible = emerging.crop((0, round(slot[1]), b.w, b.h))
                front_prints.alpha_composite(visible, (0, round(slot[1])))
        camera_alpha = 1-smooth(merge/.70)
        if camera_alpha > 0:
            center = (self.camera_center[0]-merge*b.w*.08, self.camera_center[1])
            centered(frame, opacity(self.camera, camera_alpha), center)
            for shot in self.shots:
                dt = time-shot
                if 0 <= dt < .12:
                    glow = Image.new("RGBA", frame.size)
                    x, y = center[0]-self.camera.width*.23, center[1]-self.camera.height*.22
                    radius = self.camera.width*.035
                    ImageDraw.Draw(glow).ellipse((x-radius, y-radius, x+radius, y+radius),
                                                fill=(255, 248, 218, round(115*(1-dt/.12))))
                    frame.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(1, radius*.25))))
            frame.alpha_composite(front_prints)
        if merge > .25:
            # The aligned stack becomes the cloth cover; lettering remains absent here.
            frame = Image.blend(frame, self.blank_book(0, cover_clock), smooth((merge-.25)/.75))
        return frame

    def timeline(self):
        if self.mode == "cover":
            return {"mode": "cover", "duration": 0, "shots": []}
        return {"mode": self.mode, "duration": self.duration, "shots": self.shots,
                "hero_hold": self.hero_hold, "camera_start": self.camera_offset,
                "photo_indices": self.photo_indices, "max_prints": 5,
                "has_title": self.has_title, "animated_photos": [source.animated for source in self.card_sources],
                "stack_complete": self.stack_complete, "merge_start": self.merge_start,
                "merge_complete": self.merge_complete, "title_start": self.title_start,
                "title_complete": self.title_complete, "book_open_start": self.duration}
