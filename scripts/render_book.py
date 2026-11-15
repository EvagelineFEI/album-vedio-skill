#!/usr/bin/env python3
"""Render prepared photos/cutouts as a turning memory book; no image-generation API."""

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from book_design import resolve_theme, gradient, material, page_composition, contrast, mix
from book_intro import CameraIntro
import book_cover
from album_inputs import photo_items, flatten_items, left_photo_boxes
from album_media import MediaSource

RATE = 44100
SKILL = Path(__file__).resolve().parents[1]


def clamp(x):
    return max(0.0, min(1.0, x))


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def frame_count(seconds, fps):
    """Round up once so edits never shift another segment's sampling phase."""
    return math.ceil(seconds*fps-1e-8)


def ffmpeg_exe():
    found = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as e:
        raise ValueError("MP4/audio needs ffmpeg or the imageio-ffmpeg Python package.") from e


def read_audio(path):
    result = subprocess.run(
        [ffmpeg_exe(), "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2",
         "-ar", str(RATE), "pipe:1"], capture_output=True, check=True)
    audio = np.frombuffer(result.stdout, dtype="<f4").reshape(-1, 2).copy()
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError(f"Empty or invalid audio: {path}")
    return audio


def open_image(path):
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert("RGBA")


def paste_center(canvas, image, center):
    canvas.alpha_composite(image, (round(center[0] - image.width / 2),
                                   round(center[1] - image.height / 2)))


def paste_quad(canvas, image, quad, shade=1):
    """Inverse homography into a tight rectangle, also used for curved page strips."""
    xs, ys = zip(*quad)
    left, top = math.floor(min(xs)), math.floor(min(ys))
    width, height = math.ceil(max(xs)) - left, math.ceil(max(ys)) - top
    if width < 1 or height < 1:
        return
    target = [(x - left, y - top) for x, y in quad]
    source = [(0, 0), (image.width, 0), (image.width, image.height), (0, image.height)]
    matrix, vector = [], []
    for (x, y), (u, v) in zip(target, source):
        matrix.extend([[x, y, 1, 0, 0, 0, -u*x, -u*y],
                       [0, 0, 0, x, y, 1, -v*x, -v*y]])
        vector.extend([u, v])
    try:
        coeff = np.linalg.solve(np.asarray(matrix), np.asarray(vector))
    except np.linalg.LinAlgError:
        return
    tile = image.transform((width, height), Image.Transform.PERSPECTIVE, coeff,
                           Image.Resampling.BICUBIC)
    if shade < 1:
        channels = list(tile.split())
        channels[:3] = [c.point(lambda p: int(p * shade)) for c in channels[:3]]
        tile = Image.merge("RGBA", channels)
    canvas.alpha_composite(tile, (left, top))


def floating_quad(image, center, t, phase, strength, scale, rotation=0):
    yaw = math.radians(6 * math.sin(t * 1.2 + phase) * strength)
    pitch = math.radians(3 * math.cos(t * 1.1 + phase) * strength)
    roll = math.radians(rotation + 1.6 * math.sin(t * 1.6 + phase) * strength)
    focal = max(image.size) * 4
    result = []
    for x, y in [(-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5)]:
        x, y = x * image.width * scale, y * image.height * scale
        xx, zz = x * math.cos(yaw), -x * math.sin(yaw)
        yy, z = y * math.cos(pitch) - zz * math.sin(pitch), y * math.sin(pitch) + zz * math.cos(pitch)
        xr = xx * math.cos(roll) - yy * math.sin(roll)
        yr = xx * math.sin(roll) + yy * math.cos(roll)
        perspective = focal / (focal - z)
        result.append((center[0] + xr * perspective, center[1] + yr * perspective))
    return result


def paper_texture(size, color, side, seed=5):
    w, h = size
    rng = np.random.default_rng(seed)
    rgb = np.array(Image.new("RGB", (1, 1), color), dtype=np.float32)[0, 0]
    x = np.arange(w, dtype=np.float32) / w
    crease = np.exp(-(x if side == "right" else 1 - x) / .045) * 27
    noise = rng.normal(0, .65, (h, w, 1))
    array = rgb[None, None, :] - crease[None, :, None] + noise
    return Image.fromarray(np.uint8(np.clip(array, 0, 255))).convert("RGBA")


def sprite_with_shadow(image, size):
    image = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
    pad = max(6, round(max(size) * .09))
    out = Image.new("RGBA", (image.width + 2*pad, image.height + 2*pad))
    mask = Image.new("L", out.size)
    mask.paste(image.getchannel("A"), (pad + round(pad*.25), pad + round(pad*.45)))
    mask = mask.filter(ImageFilter.GaussianBlur(pad*.38)).point(lambda p: int(p*.24))
    shadow = Image.new("RGBA", out.size, "#342c22")
    shadow.putalpha(mask)
    out.alpha_composite(shadow)
    out.alpha_composite(image, (pad, pad))
    return out


def glyph_layout(text, font, max_width, line_height, tracking=0):
    # Balance short handwritten lines and prefer punctuation over one-character widows.
    lines = []
    for paragraph in text.split("\n"):
        remaining = list(paragraph)
        if not remaining:
            lines.append("")
        while remaining:
            widths = [font.getlength(c)+tracking for c in remaining]
            total = sum(widths)
            if total <= max_width:
                lines.append("".join(remaining))
                break
            nlines = math.ceil(total / max_width)
            target = total / nlines
            cumulative, candidates = 0, []
            for i, width in enumerate(widths):
                cumulative += width
                if cumulative > max_width:
                    break
                char = remaining[i]
                following = remaining[i+1] if i+1 < len(remaining) else ""
                score = abs(cumulative-target)/max(target, 1)
                if char in "，。！？；、,.!?; ":
                    score -= .22
                if following and following in "，。！？；、,.!?;：:）)]』」”:…":
                    score += 1
                if char in "（([『「“":
                    score += 1
                if char.isascii() and char.isalnum() and following.isascii() and following.isalnum():
                    score += .45
                candidates.append((score, i+1))
            if not candidates:
                raise ValueError("A caption character exceeds the available page width.")
            cut = min(candidates)[1]
            lines.append("".join(remaining[:cut]))
            remaining = remaining[cut:]
    positions = []
    y = 0
    for line in lines:
        x = 0
        for char in line:
            positions.append((char, x, y))
            x += font.getlength(char)+tracking
        y += line_height
    return positions, max(y, line_height)


class Scene:
    def __init__(self, config, book, number):
        self.config, self.book, self.number = config, book, number
        w, h = book.pw, book.ph
        self.text = str(config.get("caption", ""))
        if book.config.get("caption_policy") == "observational-poetry" and not config.get("caption_verbatim", False):
            normalize = lambda text: "".join(c for c in text if c.isalnum())
            narration = str(config.get("narration", ""))
            if normalize(self.text) and normalize(self.text) == normalize(narration):
                raise ValueError(f"Scene {number}: page caption repeats the narration; write an image-led companion line.")
        elements = config.get("elements", [])
        if not 1 <= len(elements) <= 6:
            raise ValueError(f"Scene {number}: supply 1–6 prepared transparent elements.")
        self.composition = page_composition(config, len(elements), number, len(self.text))
        self.theme = dict(book.theme)
        self.theme.update(config.get("theme", {}))
        if contrast(self.theme["ink"], self.theme["paper"]) < 4.5:
            raise ValueError(f"Scene {number}: handwriting contrast is below 4.5:1.")
        self.ink = Image.new("RGB", (1, 1), self.theme["ink"]).getpixel((0, 0))
        self.paper_left = material((w, h), self.theme["paper"], "paper", book.materials, book.asset, "left", 5+number)
        self.paper_right = material((w, h), self.theme["paper"], "paper", book.materials, book.asset, "right", 5+number)
        scene_background = gradient((book.w, book.h), self.theme["background_gradient"]) if "background_gradient" in config.get("theme", {}) else book.background
        self.stage = book.make_stage(True, background=scene_background)
        self.photo_sources = [book.media(item, (w, h)) for item in photo_items(config)]
        aspects = [source.frame(0).width/source.frame(0).height for source in self.photo_sources]
        self.photo_boxes = left_photo_boxes(aspects, w, h, config)
        self._left_cache = {}
        self.left = self.left_at(0)
        self.sprites, self.element_kinds, self.sprite_sources, self.sprite_sizes = [], [], [], []
        self._sprite_cache = {}
        for element, placement in zip(elements, self.composition["elements"]):
            element = {"file": element} if isinstance(element, str) else element
            source = book.media(element, (w, h))
            im = source.frame(0)
            if im.getchannel("A").getextrema()[0] >= 250:
                raise ValueError(f"Scene {number}: {element['file']} lacks real transparency.")
            box = im.getchannel("A").getbbox()
            if not box and not source.animated:
                raise ValueError(f"Scene {number}: empty cutout {element['file']}")
            x, y, sw, sh = placement["box"]
            size = (max(2, round(sw*w*.86)), max(2, round(sh*h*.86)))
            sprite = sprite_with_shadow(im if source.animated else im.crop(box), size)
            sprite = ImageOps.contain(sprite, (round(sw*w*.97), round(sh*h*.97)), Image.Resampling.LANCZOS)
            self.sprites.append((sprite, ((x+sw/2)*w, (y+sh/2)*h), float(placement.get("rotation", 0))))
            self.element_kinds.append(element.get("kind", "unspecified"))
            self.sprite_sources.append(source)
            self.sprite_sizes.append((size, (round(sw*w*.97), round(sh*h*.97))))
        for decor in self.composition.get("decorations", []):
            if decor.get("kind", "wash") != "wash":
                raise ValueError("Only wash decorations are supported; use prepared PNGs for other art.")
            x, y, sw, sh = decor["box"]
            layer = Image.new("RGBA", (round(sw*w), round(sh*h)))
            color = Image.new("RGB", (1, 1), decor.get("color", self.theme["accent"])).getpixel((0, 0))
            alpha = round(255*float(decor.get("opacity", .10)))
            ImageDraw.Draw(layer).rounded_rectangle((0, 0, layer.width-1, layer.height-1), radius=max(2, layer.height//14), fill=(*color, alpha))
            layer = layer.rotate(float(decor.get("rotation", -2)), Image.Resampling.BICUBIC, expand=True)
            paste_center(self.paper_right, layer, ((x+sw/2)*w, (y+sh/2)*h))
        style = dict(book.config.get("typography", {}))
        style.update(self.composition["text"].get("style", {}))
        self.width_scale = float(style.get("width_scale", .87))
        if not .70 <= self.width_scale <= 1.1:
            raise ValueError("Handwriting width_scale must be .70–1.10.")
        x, y, tw, th = self.composition["text"]["box"]
        self.text_rect = (round(x*w), round(y*h), round(tw*w), round(th*h))
        _, _, rw, rh = self.text_rect
        font_size = round(h*float(style.get("font_scale", .067)))
        while True:
            self.font = ImageFont.truetype(str(book.font_file), font_size)
            tracking = font_size*float(style.get("tracking", .045))
            self.glyphs, text_h = glyph_layout(self.text, self.font, rw*.90/self.width_scale,
                                              round(font_size*float(style.get("line_height", 1.48))), tracking)
            preserve_breaks = bool(style.get("preserve_breaks", book.config.get("caption_policy") == "observational-poetry"))
            widest_line = max((sum(self.font.getlength(c)+tracking for c in line) for line in self.text.split("\n")), default=0)
            if text_h <= rh*.90 and (not preserve_breaks or widest_line <= rw*.90/self.width_scale):
                break
            font_size -= 1
            if font_size < max(9, round(h*.030)):
                raise ValueError(f"Scene {number}: caption does not fit this composition; enlarge its box or change layout.")
        self.element_start, self.gap = .65, .78
        self.caption_start = self.element_start+(len(elements)-1)*self.gap+.68
        self.write_time = max(1.5, len(self.glyphs)/9) if self.glyphs else 0
        self.read_time = max(2.2, len(self.glyphs)/7)
        self.voice = read_audio(book.asset(config["voiceover"])) if config.get("voiceover") else None
        needed = max(self.caption_start+self.write_time+self.read_time,
                     (len(self.voice)/RATE+.7) if self.voice is not None else 0)
        self.duration = float(config.get("duration", max(9.5, needed)))
        if not math.isfinite(self.duration) or self.duration+.001 < needed:
            raise ValueError(f"Scene {number}: duration must be at least {needed:.2f}s.")
        self.start = 0

    def left_at(self, time):
        key = tuple(source.index_at(time) for source in self.photo_sources)
        if key not in self._left_cache:
            b = self.book
            page = self.paper_left.copy()
            for i, (source, box) in enumerate(zip(self.photo_sources, self.photo_boxes)):
                x, y, sw, sh = box
                photo = ImageOps.contain(source.frame(time), (max(2, round(sw*b.pw*.91)), max(2, round(sh*b.ph*.91))), Image.Resampling.LANCZOS)
                border = max(2, round(b.pw*.018))
                matte = Image.new("RGBA", (photo.width+border*2, photo.height+border*2), "#fffdf8")
                paste_center(matte, photo, (matte.width/2, matte.height/2))
                matte = sprite_with_shadow(matte, matte.size)
                matte = ImageOps.contain(matte, (max(2, round(sw*b.pw)), max(2, round(sh*b.ph))), Image.Resampling.LANCZOS)
                angle = float(self.config.get("photo_rotation", -1 if (self.number+i) % 2 else 1))
                if abs(angle) > 4:
                    raise ValueError("Photo rotation must stay within four degrees.")
                matte = matte.rotate(angle, Image.Resampling.BICUBIC, expand=True)
                paste_center(page, matte, ((x+sw/2)*b.pw, (y+sh/2)*b.ph))
            self._left_cache[key] = page
            if len(self._left_cache) > 8:
                self._left_cache.pop(next(iter(self._left_cache)))
        return self._left_cache[key]

    def sprite_at(self, index, time):
        source = self.sprite_sources[index]
        if not source.animated:
            return self.sprites[index][0]
        key = (index, source.index_at(time))
        if key not in self._sprite_cache:
            size, bounds = self.sprite_sizes[index]
            sprite = sprite_with_shadow(source.frame(time), size)
            self._sprite_cache[key] = ImageOps.contain(sprite, bounds, Image.Resampling.LANCZOS)
            if len(self._sprite_cache) > 12:
                self._sprite_cache.pop(next(iter(self._sprite_cache)))
        return self._sprite_cache[key]

    def text_layer(self, progress):
        b = self.book
        _, _, rw, rh = self.text_rect
        native_width = max(1, round(rw/self.width_scale))
        layer = Image.new("RGBA", (native_width, rh))
        draw = ImageDraw.Draw(layer)
        extents = {}
        for char, x, y in self.glyphs:
            extents[y] = max(extents.get(y, 0), x+self.font.getlength(char))
        align = self.composition["text"].get("align", "left")
        for i, (char, x, y) in enumerate(self.glyphs):
            alpha = round(255*clamp((progress-i)*2))
            if alpha:
                available = native_width*.90
                offset = (available-extents[y])/2 if align == "center" else available-extents[y] if align == "right" else 0
                baseline = math.sin(i*2.13)*self.font.size*.014
                draw.text((native_width*.05+x+offset, rh*.05+y+baseline), char, font=self.font,
                          fill=(*self.ink, alpha), anchor="lt")
        layer = layer.resize((rw, rh), Image.Resampling.LANCZOS)
        angle = float(self.composition["text"].get("rotation", 0))
        if abs(angle) > 5:
            raise ValueError("Handwriting rotation must stay within five degrees.")
        return layer.rotate(angle, Image.Resampling.BICUBIC, expand=False)

    def right(self, time, flat=False):
        b = self.book
        page = self.paper_right.copy()
        settle = smooth((self.duration-time)/.4)
        for i, (sprite, center, rotation) in enumerate(self.sprites):
            elapsed = time-self.element_start-i*self.gap
            if elapsed <= 0:
                continue
            sprite = self.sprite_at(i, elapsed)
            enter = clamp(elapsed/.55)
            ease = 1+2.4*(enter-1)**3+1.4*(enter-1)**2
            scale = .80+.20*ease
            strength = b.motion*settle*(0 if flat else 1)
            x = center[0]+math.sin(elapsed*1.5+i*2.1)*b.pw*.003*strength
            y = center[1]+(1-smooth(enter))*b.ph*.035-math.sin(elapsed*1.3+i)*b.ph*.005*strength
            quad = floating_quad(sprite, (x, y), elapsed, i*2.1, strength, scale, rotation)
            fade_sprite = sprite
            if enter < .35:
                fade_sprite = sprite.copy()
                fade_sprite.putalpha(sprite.getchannel("A").point(lambda p: round(p*smooth(enter/.35))))
            paste_quad(page, fade_sprite, quad)
        if self.glyphs and time > self.caption_start:
            progress = clamp((time-self.caption_start)/self.write_time)*len(self.glyphs)
            page.alpha_composite(self.text_layer(progress), self.text_rect[:2])
        return page


class Book:
    def __init__(self, manifest):
        self.path = Path(manifest).resolve()
        self.config = json.loads(self.path.read_text(encoding="utf-8"))
        self._media_sources = {}
        title = self.config.get("intake", {}).get("title", {})
        if title.get("mode") == "none":
            self.config["title"] = ""
            self.config["subtitle"] = ""
        elif title.get("value"):
            self.config["title"] = title["value"]
        self.w, self.h = [int(x) for x in self.config.get("size", [1920, 1080])]
        self.fps = int(self.config.get("fps", 30))
        if min(self.w, self.h) < 240 or max(self.w, self.h) > 3840 or self.w % 2 or self.h % 2:
            raise ValueError("Use even frame dimensions, minimum 240px, maximum 3840px.")
        if not 1 <= self.fps <= 60:
            raise ValueError("fps must be 1–60.")
        self.recipe = book_cover.resolve_recipe(self.config)
        ratio = self.recipe["ratio"]
        self.pw = round(min(self.w*.445, self.h*.80*ratio))
        self.ph = round(self.pw/ratio)
        self.cx, self.top = self.w//2, (self.h-self.ph)//2
        self.left_x = self.cx-self.pw
        self.opening = float(self.config.get("opening", 1.5))
        self.turn = float(self.config.get("page_turn", 1.25))
        self.final_hold = float(self.config.get("final_hold", 1.0))
        self.motion = float(self.config.get("motion", .8))
        if not .4 <= self.opening <= 5 or not .4 <= self.turn <= 5 or not 0 <= self.final_hold <= 30:
            raise ValueError("Opening/turn must be .4–5s; final_hold must be 0–30s.")
        if not 0 <= self.motion <= 1.5:
            raise ValueError("motion must be 0–1.5.")
        self.opening = frame_count(self.opening, self.fps)/self.fps
        self.turn = frame_count(self.turn, self.fps)/self.fps
        self.final_hold = frame_count(self.final_hold, self.fps)/self.fps
        self.font_file = self.asset(self.config["font"]) if self.config.get("font") else SKILL/"assets/fonts/LongCang-Regular.ttf"
        configs = self.config.get("scenes", [])
        if not configs:
            raise ValueError("scenes cannot be empty.")
        self.photo_items = flatten_items(configs)
        photos = [self.media(item, (128, 128)).frame(0).convert("RGB") for item in self.photo_items]
        cover_index = int(self.config.get("cover_photo_index", 0))
        if not 0 <= cover_index < len(self.photo_items):
            raise ValueError("cover_photo_index must refer to an original project photo, not a page number.")
        self.cover_media = self.media(self.photo_items[cover_index], (self.pw, self.ph))
        self._cover_cache = {}
        brief = self.config.get("title", "")+" "+self.config.get("narration_source", "")
        self.theme = resolve_theme(photos, self.config.get("theme", {}), brief)
        self.theme = book_cover.cover_theme(self.theme, self.config.get("theme", {}), self.recipe)
        self.materials = self.config.get("materials", {})
        self.ink = Image.new("RGB", (1, 1), self.theme["ink"]).getpixel((0, 0))
        self.paper_left = material((self.pw, self.ph), self.theme["paper"], "paper", self.materials, self.asset, "left")
        self.paper_right = material((self.pw, self.ph), self.theme["paper"], "paper", self.materials, self.asset, "right")
        self.background = self.make_background()
        self.open_stage = self.make_stage(True)
        self.closed_stage = self.make_stage(False)
        self.cover_plain = self.make_cover()
        self.cover_title = self.make_title_layer()
        self.cover = self.cover_plain.copy()
        self.cover.alpha_composite(self.cover_title)
        self.intro = CameraIntro(self, self.photo_items)
        self.prologue = frame_count(self.intro.duration, self.fps)/self.fps
        self.intro.duration = self.prologue
        self.scenes = [Scene(c, self, i+1) for i, c in enumerate(configs)]
        cursor = round((self.prologue+self.opening)*self.fps)
        for i, scene in enumerate(self.scenes):
            scene.duration = frame_count(scene.duration, self.fps)/self.fps
            scene.incoming = self.opening if i == 0 else self.turn
            scene.start = cursor/self.fps
            scene.visible_start = scene.start-scene.incoming
            cursor += round((scene.duration+self.turn)*self.fps)
        self.total = (cursor-round(self.turn*self.fps)+round(self.final_hold*self.fps))/self.fps

    def asset(self, filename):
        p = (self.path.parent / filename).resolve()
        if not p.is_file():
            raise ValueError(f"Missing asset: {p}")
        return p

    def media(self, item, size):
        item = {"file": str(item)} if isinstance(item, (str, Path)) else dict(item)
        key = (json.dumps(item, ensure_ascii=False, sort_keys=True), tuple(size))
        if key not in self._media_sources:
            self._media_sources[key] = MediaSource(item, self.asset, size, ffmpeg_exe)
        return self._media_sources[key]

    def cover_at(self, time, with_title=True):
        if self.recipe["enabled"] and self.cover_media.animated:
            key = self.cover_media.index_at(time)
            if key not in self._cover_cache:
                self._cover_cache[key] = book_cover.plain_cover(self, time)
                if len(self._cover_cache) > 8:
                    self._cover_cache.pop(next(iter(self._cover_cache)))
            cover = self._cover_cache[key].copy()
        else:
            cover = self.cover_plain.copy()
        if with_title:
            cover.alpha_composite(self.cover_title)
        return cover

    def page_left_at(self, scene, time):
        return scene.left_at(max(0, time-scene.visible_start))

    def make_background(self):
        base = gradient((self.w, self.h), self.theme["background_gradient"])
        return book_cover.atmospheric_background(self, base)

    def hero_cover_frame(self, time):
        return book_cover.hero_frame(self, time, paste_quad)

    def make_stage(self, opened, background=None):
        image = (background if background is not None else self.background).copy()
        left = self.left_x if opened else self.cx
        bounds = (left-8, self.top-6, self.cx+self.pw+9, self.top+self.ph+13)
        shadow = Image.new("RGBA", image.size)
        ImageDraw.Draw(shadow).rounded_rectangle(
            (bounds[0]-3, bounds[1]+14, bounds[2]+10, bounds[3]+18), radius=12, fill=(15, 26, 22, 100))
        image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(3, self.w*.012))))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(bounds, radius=max(4, self.w//220), fill=self.theme["cover"])
        for offset in [3, 6, 9]:
            draw.line((left, self.top+self.ph+offset, self.cx+self.pw, self.top+self.ph+offset),
                      fill="#b9b0a0", width=1)
        return image

    def make_cover(self):
        if self.recipe["enabled"]:
            return book_cover.plain_cover(self)
        cover = material((self.pw, self.ph), self.theme["cover"], "cover", self.materials, self.asset)
        draw = ImageDraw.Draw(cover)
        margin = self.pw*.065
        foil = self.theme.get("foil", mix(self.theme["accent"], "#e6debd", .65))
        draw.rounded_rectangle((margin, margin, self.pw-margin, self.ph-margin), radius=3,
                               outline=foil, width=max(1, self.pw//330))
        draw.line((self.pw*.035, margin, self.pw*.035, self.ph-margin),
                  fill=mix(self.theme["cover"], "#000000", .22), width=max(1, self.pw//280))
        return cover

    def make_title_layer(self):
        if self.recipe["enabled"]:
            return book_cover.title_layer(self)
        layer = Image.new("RGBA", (self.pw, self.ph))
        title = str(self.config.get("title", ""))
        if not title:
            return layer
        ink = self.theme.get("cover_ink", "#f8eed4" if contrast(self.theme["cover"], "#f8eed4") >
                             contrast(self.theme["cover"], "#29251d") else "#29251d")
        fontsize = round(self.pw*.13)
        while True:
            font = ImageFont.truetype(str(self.font_file), fontsize)
            box = ImageDraw.Draw(layer).multiline_textbbox((0, 0), title, font=font, spacing=round(fontsize*.35))
            if box[2]-box[0] <= self.pw*.78 and box[3]-box[1] <= self.ph*.42:
                break
            fontsize -= 1
            if fontsize < 12:
                raise ValueError("Book title is too long.")
        draw = ImageDraw.Draw(layer)
        draw.multiline_text((self.pw*.5, self.ph*.43), title, font=font, fill=ink,
                            spacing=round(fontsize*.35), anchor="mm", align="center")
        subtitle = str(self.config.get("subtitle", ""))
        if subtitle:
            small = ImageFont.truetype(str(self.font_file), round(self.pw*.057))
            if small.getlength(subtitle) > self.pw*.78:
                raise ValueError("Cover subtitle is too long.")
            draw.line((self.pw*.34, self.ph*.57, self.pw*.66, self.ph*.57), fill=ink, width=max(1, self.pw//450))
            draw.text((self.pw*.5, self.ph*.63), subtitle, font=small, fill=ink, anchor="mt")
        return layer

    def put_pages(self, left, right, closed=False, stage=None):
        frame = (stage if stage is not None else self.closed_stage if closed else self.open_stage).copy()
        if left is not None:
            frame.alpha_composite(left, (self.left_x, self.top))
        frame.alpha_composite(right, (self.cx, self.top))
        return frame

    def turn_sheet(self, frame, front, back, progress):
        p = smooth(progress)
        angle = math.pi*p
        focal = self.pw*4.5
        mid_y = self.top+self.ph/2

        def point(u, bottom=False):
            # A gently curling leaf around a fixed spine, projected in 3D.
            a = angle + .24*math.sin(angle)*u
            x = self.pw*u*math.cos(a)
            z = self.pw*u*math.sin(a)
            k = focal/(focal-z)
            y = self.ph/2 if bottom else -self.ph/2
            return (self.cx+x*k, mid_y+y*k), z

        # Moving soft shadow belongs to the page, separate from printed contents.
        outer_t, _ = point(1)
        outer_b, _ = point(1, True)
        shadow = Image.new("RGBA", frame.size)
        q = [(self.cx, self.top+5), (outer_t[0]+10, outer_t[1]+15),
             (outer_b[0]+10, outer_b[1]+15), (self.cx, self.top+self.ph+5)]
        ImageDraw.Draw(shadow).polygon(q, fill=(37, 30, 23, round(48*math.sin(angle))))
        frame.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(2, self.w*.006))))
        strips = []
        # Shared integer boundaries avoid texture seams between adjacent strips.
        edges = np.linspace(0, self.pw, 49, dtype=int)
        for x0, x1 in zip(edges[:-1], edges[1:]):
            if x1 <= x0:
                continue
            u0, u1 = x0/self.pw, x1/self.pw
            tl, z0 = point(u0)
            tr, z1 = point(u1)
            bl, _ = point(u0, True)
            br, _ = point(u1, True)
            visible_front = tr[0] >= tl[0]
            if visible_front:
                tile = front.crop((x0, 0, x1, self.ph))
                quad = [tl, tr, br, bl]
            else:
                tile = back.crop((self.pw-x1, 0, self.pw-x0, self.ph))
                quad = [tr, tl, bl, br]
            shade = .87+.13*abs(math.cos(angle+.24*math.sin(angle)*(u0+u1)/2))
            strips.append(((z0+z1)/2, tile, quad, shade))
        for _, tile, quad, shade in sorted(strips, key=lambda s: s[0]):
            paste_quad(frame, tile, quad, shade)
        return frame

    def segment_frame(self, kind, index, local):
        """Sample in segment-local time, independent of earlier pages' lengths."""
        if kind == "intro":
            return self.intro.frame(local)
        if kind == "opening":
            frame = self.put_pages(None, self.scenes[0].paper_right, closed=True)
            return self.turn_sheet(frame, self.cover_at(local), self.scenes[0].left_at(local), local/self.opening)
        scene = self.scenes[index]
        if kind == "page":
            return self.put_pages(scene.left_at(local+scene.incoming), scene.right(local), stage=scene.stage)
        if kind == "ending":
            return self.put_pages(scene.left_at(scene.duration+scene.incoming+local),
                                  scene.right(scene.duration), stage=scene.stage)
        if kind == "turn":
            next_scene = self.scenes[index+1]
            stage = Image.blend(scene.stage, next_scene.stage, smooth(local/self.turn))
            frame = self.put_pages(scene.left_at(scene.duration+scene.incoming+local), next_scene.paper_right, stage=stage)
            return self.turn_sheet(frame, scene.right(scene.duration, flat=True), next_scene.left_at(local), local/self.turn)
        raise ValueError(f"Unknown segment kind: {kind}")

    def frame(self, time):
        if time < self.prologue:
            return self.segment_frame("intro", None, time)
        if time < self.prologue+self.opening:
            return self.segment_frame("opening", 0, time-self.prologue)
        for i, scene in enumerate(self.scenes):
            end = scene.start+scene.duration
            if time < end:
                return self.segment_frame("page", i, time-scene.start)
            if i == len(self.scenes)-1:
                return self.segment_frame("ending", i, time-end)
            if time < end+self.turn:
                return self.segment_frame("turn", i, time-end)
        raise RuntimeError("Timeline not covered")

    def timeline(self):
        return {"size": [self.w, self.h], "fps": self.fps, "duration": self.total,
                "intro": self.intro.timeline(), "resolved_theme": self.theme,
                "cover_recipe": self.recipe, "cover_font_usage": getattr(self, "cover_font_usage", {}),
                "caption_policy": self.config.get("caption_policy", "legacy"),
                "intake": self.config.get("intake", {}),
                "element_rendering": "transparent sprites with 2.5D movement",
                "caption_rendering": "handwriting font, character reveal (not stroke tracing)",
                "music": self.config.get("music", {"mode": "synth", "mood": "calm"}),
                "scenes": [{"index": s.number, "start": s.start, "duration": s.duration,
                            "caption": s.text, "narration": s.config.get("narration", ""),
                            "composition": s.composition, "element_kinds": s.element_kinds,
                            "caption_source": s.config.get("caption_source", "unspecified"),
                            "photos": [source.info() for source in s.photo_sources],
                            "animated_elements": [source.animated for source in s.sprite_sources],
                            "photo_boxes": s.photo_boxes, "group_key": s.config.get("group_key"),
                            "voiceover": s.config.get("voiceover"),
                            "element_times": [s.start+s.element_start+i*s.gap for i in range(len(s.sprites))],
                            "caption_start": s.start+s.caption_start,
                            "caption_complete": s.start+s.caption_start+s.write_time,
                            "turn_start": s.start+s.duration if s.number < len(self.scenes) else None}
                           for s in self.scenes]}


def add_audio(destination, sound, start, gain=1):
    start = max(0, round(start*RATE))
    n = min(len(sound), len(destination)-start)
    if n > 0:
        if sound.ndim == 1:
            sound = np.repeat(sound[:, None], 2, axis=1)
        destination[start:start+n] += sound[:n]*gain


def synth_music(duration, mood, bpm):
    """A continuous original, simple synthesized score, not sampled instruments."""
    output = np.zeros((math.ceil(duration*RATE), 2), np.float32)
    if mood not in {"calm", "nostalgic", "playful", "urban", "dreamy"}:
        raise ValueError("Unknown music mood.")
    beat = 60/bpm
    minor = mood in {"nostalgic", "urban"}
    chords = [(57, 60, 64), (53, 57, 60), (60, 64, 67), (55, 59, 62)] if minor else [
        (60, 64, 67), (57, 60, 64), (53, 57, 60), (55, 59, 62)]
    for bar, start in enumerate(np.arange(0, duration, beat*4)):
        chord = chords[bar % len(chords)]
        t = np.arange(round((beat*4+.5)*RATE))/RATE
        env = np.minimum(t/.35, 1)*np.clip((beat*4+.5-t)/.7, 0, 1)
        pad = sum(np.sin(2*np.pi*(440*2**((note-69)/12))*t + i*.3) for i, note in enumerate(chord))
        add_audio(output, (pad*env*.022).astype(np.float32), start)
        step = beat if mood == "dreamy" else beat*.5
        for j, offset in enumerate(np.arange(0, beat*4, step)):
            note = chord[[0, 1, 2, 1, 2, 1, 0, 1][j % 8]] + 12
            freq = 440*2**((note-69)/12)
            nt = np.arange(round(beat*1.5*RATE))/RATE
            env = np.minimum(nt/.012, 1)*np.exp(-nt/(.5 if mood != "playful" else .22))
            tone = (np.sin(2*np.pi*freq*nt)+.16*np.sin(4*np.pi*freq*nt))*env*.050
            pan = .25 if j % 2 else -.25
            stereo = np.column_stack([tone*(1-pan), tone*(1+pan)]).astype(np.float32)
            add_audio(output, stereo, start+offset)
        bt = np.arange(round(beat*3.5*RATE))/RATE
        bass = np.sin(2*np.pi*(440*2**((chord[0]-24-69)/12))*bt)*np.minimum(bt/.03, 1)*np.exp(-bt/1.1)*.04
        add_audio(output, bass.astype(np.float32), start)
    return output


def loop_music(audio, samples):
    if len(audio) >= samples:
        return audio[:samples].copy()
    output = np.zeros((samples, 2), np.float32)
    cross = min(RATE//2, len(audio)//4)
    hop = len(audio)-cross
    for start in range(0, samples, hop):
        clip = audio.copy()
        if cross:
            if start:
                clip[:cross] *= np.linspace(0, 1, cross)[:, None]
            clip[-cross:] *= np.linspace(1, 0, cross)[:, None]
        n = min(len(clip), samples-start)
        output[start:start+n] += clip[:n]
    return output


def audio_mix(book):
    config = book.config.get("music", {})
    mode, mood = config.get("mode", "synth"), config.get("mood", "calm")
    bpm = float(config.get("bpm", {"calm": 76, "nostalgic": 70, "playful": 100,
                                  "urban": 84, "dreamy": 68}.get(mood, 76)))
    if not 40 <= bpm <= 180:
        raise ValueError("BPM must be 40–180.")
    samples = math.ceil(book.total*RATE)
    if mode == "synth":
        music = synth_music(book.total, mood, bpm)
    elif mode == "file":
        music = loop_music(read_audio(book.asset(config["file"])), samples)
    elif mode == "none":
        music = np.zeros((samples, 2), np.float32)
    else:
        raise ValueError("music.mode must be synth, file or none.")
    # Detect real speech energy at 10ms intervals and smooth ducking around it.
    voice = np.zeros_like(music)
    for scene in book.scenes:
        if scene.voice is not None:
            add_audio(voice, scene.voice, scene.start+.2)
    block = RATE//100
    nblocks = math.ceil(samples/block)
    energy = np.max(np.abs(np.pad(voice, ((0, nblocks*block-samples), (0, 0))).reshape(nblocks, block, 2)), axis=(1, 2))
    kernel = np.ones(31)/31
    active = np.clip(np.convolve((energy > .008).astype(float), kernel, mode="same")*2, 0, 1)
    duck = np.interp(np.arange(samples), np.arange(nblocks)*block, 1-.72*active)
    music *= duck[:, None]*float(config.get("gain", .8))
    mix = music + voice*.9
    if book.config.get("sfx", True):
        rng = np.random.default_rng(62)
        for shot in book.intro.shots:
            t = np.arange(round(.15*RATE))/RATE
            snap = rng.normal(0, 1, len(t))*np.exp(-t/.012)*.075
            snap += (t>.055)*rng.normal(0, 1, len(t))*np.exp(-np.maximum(0, t-.055)/.013)*.046
            snap += np.sin(2*np.pi*1180*t)*np.exp(-t/.022)*.012
            add_audio(mix, snap.astype(np.float32), shot)
            t = np.arange(round(.40*RATE))/RATE
            motor = (np.sin(2*np.pi*118*t)+.28*np.sin(2*np.pi*239*t))*np.sin(np.pi*t/.40)**2*.007
            add_audio(mix, motor.astype(np.float32), shot+.07)
        flip_times = [book.prologue+.05] + [s.start+s.duration for s in book.scenes[:-1]]
        for start in flip_times:
            t = np.arange(round(.8*RATE))/RATE
            noise = rng.normal(0, 1, len(t))
            rustle = (noise-np.roll(noise, 1)) * np.sin(np.pi*t/.8)**2 * .015
            add_audio(mix, rustle.astype(np.float32), start)
        for scene in book.scenes:
            for i in range(len(scene.sprites)):
                t = np.arange(round(.16*RATE))/RATE
                tone = np.sin(2*np.pi*(210+i*35)*t)*np.exp(-t/.034)*np.minimum(t/.006, 1)*.028
                add_audio(mix, tone.astype(np.float32), scene.start+scene.element_start+i*scene.gap)
    fade_in = min(samples, round(.45*RATE))
    fade_out = min(samples, round(1.0*RATE))
    mix[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    mix[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    peak = np.max(np.abs(mix))
    if peak > .93:
        mix *= .93/peak
    return mix


def render(book, output, overwrite, cache_dir=None, rebuild_pages=(), rebuild_all=False):
    from book_cache import render_cached
    return render_cached(book, output, overwrite, ffmpeg_exe(), audio_mix, RATE,
                         cache_dir=cache_dir, rebuild_pages=rebuild_pages, rebuild_all=rebuild_all)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="project.json; asset paths are relative to this file")
    parser.add_argument("--output", default="storybook.mp4")
    parser.add_argument("--frame", type=float, help="Render one still at this time instead of an MP4")
    parser.add_argument("--frame-file", default="preview.png")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--cache-plan", action="store_true", help="Report which segments need rendering; writes no media")
    parser.add_argument("--cache-dir", help="Persistent segment cache; defaults to .album-cache/<manifest-stem>")
    parser.add_argument("--rebuild-pages", default="", help="Force page numbers and adjacent transitions, e.g. 2,4")
    parser.add_argument("--rebuild-all", action="store_true", help="Ignore existing cached segments and refresh them")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    book = Book(args.manifest)
    from book_cache import cache_plan, parse_pages
    pages = parse_pages(args.rebuild_pages, len(book.scenes))
    if args.cache_plan:
        print(json.dumps(cache_plan(book, ffmpeg_exe(), args.cache_dir, pages, args.rebuild_all, RATE).report(), ensure_ascii=False, indent=2))
    elif args.plan_only:
        print(json.dumps(book.timeline(), ensure_ascii=False, indent=2))
    elif args.frame is not None:
        if not 0 <= args.frame <= book.total:
            raise ValueError(f"Frame time must be 0–{book.total:.2f}s.")
        path = Path(args.frame_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        book.frame(args.frame).convert("RGB").save(path)
        print(path.resolve())
    else:
        render(book, args.output, args.overwrite, args.cache_dir, pages, args.rebuild_all)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(2)
