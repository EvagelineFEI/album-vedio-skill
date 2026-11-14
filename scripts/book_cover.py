"""Independent editorial cover axes and a consistent floating hardcover hero."""
import hashlib
from album_inputs import flatten_items
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from book_design import rgb, hex_color, mix, contrast, material

AXES = {
    "A": {"A1": "正方布面精装", "A2": "美术馆哑光白", "A3": "露脊线装", "A4": "暗调压印"},
    "B": {"B1": "拍立得嵌图", "B2": "微缩居中窗口", "B3": "错位出血", "B4": "撕边和纸胶带"},
    "C": {"C1": "虹彩泡泡散景", "C2": "暮色云层", "C3": "斑驳光影", "C4": "细波水面", "C5": "胶片渐变"},
    "D": {"D1": "等宽打字机", "D2": "微缩衬线", "D3": "瑞士网格"},
}


def resolve_recipe(config):
    if "cover_recipe" not in config:
        return {"enabled": False, "ratio": .88}
    supplied = config["cover_recipe"]
    canonical = json.dumps({"title": config.get("title", ""), "photos": [item["file"] for item in flatten_items(config.get("scenes", []))]}, sort_keys=True)
    seed = int(supplied.get("seed", int(hashlib.sha256(canonical.encode()).hexdigest()[:8], 16)))
    rng = np.random.default_rng(seed)
    recipe = {"enabled": True, "seed": seed}
    for axis, choices in AXES.items():
        requested = supplied.get(axis, "auto")
        if requested == "auto":
            requested = list(choices)[int(rng.integers(len(choices)))]
        if requested not in choices:
            raise ValueError(f"Unknown {axis} cover selection: {requested}")
        recipe[axis] = requested
    recipe["ratio"] = {"A1": 1.0, "A2": .75, "A3": .8, "A4": .75 if seed % 2 else 1.0}[recipe["A"]]
    recipe["declaration"] = " + ".join(f"[{recipe[a]} {AXES[a][recipe[a]]}]" for a in AXES)
    # Conservative geometric estimate includes photo/frame, typography and binding details.
    recipe["quiet_area_estimate"] = {"B1": .46, "B2": .67, "B3": .51, "B4": .53}[recipe["B"]]
    return recipe


def cover_theme(theme, supplied, recipe):
    result = dict(theme)
    if not recipe["enabled"]:
        return result
    if "cover" not in supplied:
        result["cover"] = {"A1": theme["cover"], "A2": mix(theme["paper"], "#ffffff", .40),
                           "A3": mix(theme["accent"], theme["paper"], .68),
                           "A4": mix(theme["cover"], "#17191c", .84)}[recipe["A"]]
    return result


def atmospheric_background(book, base):
    if not book.recipe["enabled"]:
        return base
    config = book.config.get("backdrop", {})
    if config.get("asset"):
        with Image.open(book.asset(config["asset"])) as image:
            return ImageOps.fit(image.convert("RGBA"), base.size, method=Image.Resampling.LANCZOS)
    w, h = base.size
    rng = np.random.default_rng(book.recipe["seed"]+71)
    kind = book.recipe["C"]
    if kind == "C1":
        layer = Image.new("RGBA", base.size)
        draw = ImageDraw.Draw(layer)
        for i in range(10):
            x = float(rng.uniform(.03, .97))*w
            if .32*w < x < .68*w:
                x = .12*w if i % 2 else .88*w
            y, radius = float(rng.uniform(.08, .92))*h, float(rng.uniform(.018, .065))*w
            bounds = (x-radius, y-radius, x+radius, y+radius)
            draw.ellipse(bounds, fill=(246, 250, 255, 12), outline=(255, 255, 255, 70), width=max(1, w//900))
            for start, color in [(190, (218, 175, 225, 70)), (225, (170, 220, 239, 75)), (260, (250, 223, 162, 65))]:
                draw.arc(bounds, start, start+42, fill=color, width=max(1, w//700))
        base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(max(.6, w/1800))))
    elif kind == "C2":
        cloud = Image.new("RGBA", base.size)
        draw = ImageDraw.Draw(cloud)
        for _ in range(13):
            x, y = float(rng.uniform(-.15, 1.1))*w, float(rng.uniform(.05, .9))*h
            rx, ry = float(rng.uniform(.10, .25))*w, float(rng.uniform(.035, .09))*h
            draw.ellipse((x-rx, y-ry, x+rx, y+ry), fill=(245, 231, 232, int(rng.integers(16, 48))))
        base.alpha_composite(cloud.filter(ImageFilter.GaussianBlur(w*.025)))
        # Identifiable silhouettes are only used when supplied, never invented landmarks.
        if config.get("silhouette_asset"):
            with Image.open(book.asset(config["silhouette_asset"])) as image:
                silhouette = ImageOps.contain(image.convert("RGBA"), (round(w*.25), round(h*.18)))
            base.alpha_composite(silhouette, (round(w*.02), h-silhouette.height))
    elif kind == "C3":
        shadow = Image.new("RGBA", base.size)
        draw = ImageDraw.Draw(shadow)
        if config.get("gobo", "leaves") == "blinds":
            for y in np.linspace(-h*.3, h*1.2, 12):
                draw.polygon([(0, y), (w, y-h*.23), (w, y-h*.23+h*.035), (0, y+h*.035)], fill=(43, 47, 42, 27))
        else:
            for i in range(45):
                right = i % 2 == 0
                x = float(rng.uniform(.73, 1.08) if right else rng.uniform(-.08, .23))*w
                y = float(rng.uniform(-.04, .45) if right else rng.uniform(.62, 1.08))*h
                rx, ry = float(rng.uniform(.008, .035))*w, float(rng.uniform(.02, .07))*h
                draw.ellipse((x-rx, y-ry, x+rx, y+ry), fill=(45, 55, 44, 34))
        base.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(3, w*.012))))
    elif kind == "C4":
        yy, xx = np.mgrid[:h, :w].astype(np.float32)
        wave = np.sin(xx/w*44+np.sin(yy/h*29)*1.6)+np.sin(yy/h*53+np.sin(xx/w*18)*1.3)
        caustics = np.maximum(0, np.cos(wave*2.0))**14*9
        array = np.asarray(base.convert("RGB"), np.float32)+caustics[:, :, None]
        base = Image.fromarray(np.uint8(np.clip(array, 0, 255))).convert("RGBA")
    else:
        array = np.asarray(base.convert("RGB"), np.float32)
        grain = rng.normal(0, .85, (h, w, 1))
        base = Image.fromarray(np.uint8(np.clip(array+grain, 0, 255))).convert("RGBA")
    return base


def photo_box(recipe):
    return {"B1": [.16, .28, .68, .54], "B2": [.29, .34, .42, .41],
            "B3": [.40, .30 if recipe["D"] == "D2" else .36, .60, .45 if recipe["D"] == "D2" else .56],
            "B4": [.17, .29, .66, .49]}[recipe["B"]]


def plain_cover(book, time=0):
    w, h = book.pw, book.ph
    kind = book.recipe["A"]
    settings = dict(book.materials)
    if kind == "A1":
        settings["cover_strength"] = min(2, float(settings.get("cover_strength", .9))*1.2)
    cover = material((w, h), book.theme["cover"], "cover" if kind == "A1" else "paper", settings, book.asset)
    draw = ImageDraw.Draw(cover)
    # A quiet, genuinely dimensional spine groove rather than an ornamental frame.
    draw.line((w*.047, h*.015, w*.047, h*.985), fill=mix(book.theme["cover"], "#000000", .17), width=max(2, w//180))
    draw.line((w*.052, h*.015, w*.052, h*.985), fill=mix(book.theme["cover"], "#ffffff", .13), width=max(1, w//550))
    if kind == "A1":
        accent = rgb(book.theme["accent"])/255
        import colorsys
        hue, saturation, value = colorsys.rgb_to_hsv(*accent)
        band = hex_color(np.array(colorsys.hsv_to_rgb((hue+.48) % 1, max(.50, saturation), .65))*255)
        draw.rectangle((w*.075, 0, w*.105, h), fill=book.config.get("cover_band_color", band))
        draw.line((w*.105, 0, w*.105, h), fill=mix(band, "#000000", .20), width=max(1, w//300))
    elif kind == "A3":
        draw.rectangle((0, 0, w*.028, h), fill=mix(book.theme["cover"], "#000000", .24))
        for y in np.linspace(h*.11, h*.89, 8):
            draw.line((w*.008, y-3, w*.040, y+3), fill=mix(book.theme["paper"], "#ffffff", .25), width=max(1, w//250))
    photo = book.cover_media.frame(time)
    x, y, sw, sh = photo_box(book.recipe)
    box = (round(sw*w), round(sh*h))
    style = book.recipe["B"]
    if style == "B1":
        tile = Image.new("RGBA", box, "#fffdf7")
        image = ImageOps.contain(photo, (round(box[0]*.91), round(box[1]*.81)), Image.Resampling.LANCZOS)
        tile.alpha_composite(image, ((tile.width-image.width)//2, round(tile.height*.045)))
    else:
        tile = ImageOps.fit(photo, box, method=Image.Resampling.LANCZOS, centering=(.5, .43)) if style == "B3" else ImageOps.contain(photo, box, Image.Resampling.LANCZOS)
    px, py = round(x*w+(box[0]-tile.width)/2), round(y*h+(box[1]-tile.height)/2)
    if style == "B4":
        mask = Image.new("L", tile.size)
        yy = np.arange(tile.height)
        xx = np.arange(tile.width)
        left = 1.4+np.sin(yy*.19)*.8+np.sin(yy*.047)*1.1
        top = 1.4+np.sin(xx*.23)*.8+np.sin(xx*.063)*1.1
        field = (xx[None, :] >= left[:, None]) & (xx[None, :] < tile.width-1-left[:, None]) & (yy[:, None] >= top[None, :]) & (yy[:, None] < tile.height-1-top[None, :])
        mask = Image.fromarray(np.uint8(field)*255)
        tile.putalpha(mask)
    shadow = Image.new("RGBA", cover.size)
    smask = Image.new("L", cover.size)
    smask.paste(tile.getchannel("A"), (px+max(1, w//350), py+max(1, h//250)))
    shade = Image.new("RGBA", cover.size, "#28231d")
    shade.putalpha(smask.filter(ImageFilter.GaussianBlur(max(1, w*.004))).point(lambda v: round(v*.22)))
    cover.alpha_composite(shade)
    cover.alpha_composite(tile, (px, py))
    if style == "B2":
        # Shallow inset window rim.
        draw = ImageDraw.Draw(cover)
        draw.rectangle((px-1, py-1, px+tile.width, py+tile.height), outline=mix(book.theme["cover"], "#000000", .10), width=1)
    elif style == "B4":
        for tx, angle in [(px+w*.015, -8), (px+tile.width-w*.20, 7)]:
            tape = Image.new("RGBA", (round(w*.20), max(3, round(h*.035))), (226, 220, 191, 125))
            tape = tape.rotate(angle, Image.Resampling.BICUBIC, expand=True)
            cover.alpha_composite(tape, (round(tx), py-round(h*.018)))
    return cover


def cover_font(book, family, text, size):
    custom = book.config.get("cover_fonts", {}).get(family)
    cjk = any(ord(c) > 127 for c in text)
    if custom:
        candidates = [book.asset(custom)]
    elif cjk:
        candidates = [Path("/System/Library/Fonts/Supplemental/Songti.ttc")] if family == "serif" else [Path("/System/Library/Fonts/Hiragino Sans GB.ttc")]
    else:
        candidates = {"serif": [Path("/System/Library/Fonts/Supplemental/Georgia.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf")],
                      "mono": [Path("/System/Library/Fonts/Menlo.ttc"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")],
                      "sans": [Path("/System/Library/Fonts/Helvetica.ttc"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]}[family]
    available = next((p for p in candidates if p.is_file()), book.font_file)
    if not hasattr(book, "cover_font_usage"):
        book.cover_font_usage = {}
    used = book.cover_font_usage.setdefault(family, {"paths": [], "fallback": False})
    if str(available) not in used["paths"]:
        used["paths"].append(str(available))
    used["fallback"] = used["fallback"] or (available == book.font_file and not custom)
    return ImageFont.truetype(str(available), max(10, size))


def tracked_text(book, layer, text, center, size, family, max_width, ink, tracking=1.0, align="center"):
    if not text:
        return
    fontsize = round(size)
    while True:
        font = cover_font(book, family, text, fontsize)
        advances = [font.getlength(c)*tracking for c in text]
        if sum(advances) <= max_width:
            break
        fontsize -= 1
        if fontsize < 10:
            raise ValueError("Cover text is too long for the selected editorial layout.")
    total = sum(advances)
    x = center[0]-total/2 if align == "center" else center[0]-total if align == "right" else center[0]
    draw = ImageDraw.Draw(layer)
    for char, advance in zip(text, advances):
        draw.text((round(x), round(center[1])), char, font=font, fill=ink, anchor="lt")
        x += advance


def title_layer(book):
    w, h = book.pw, book.ph
    layer = Image.new("RGBA", (w, h))
    title, subtitle = str(book.config.get("title", "")), str(book.config.get("subtitle", ""))
    ink = book.theme.get("cover_ink", "#f6eee2" if contrast(book.theme["cover"], "#f6eee2") > contrast(book.theme["cover"], "#29251f") else "#29251f")
    kind = book.recipe["D"]
    if kind == "D1":
        tracked_text(book, layer, title, (w*.5, h*.12), w*.061, "mono", w*.80, ink, 1.05)
        tracked_text(book, layer, subtitle, (w*.5, h*.88), w*.025, "serif", w*.76, ink)
        metadata = book.config.get("cover_metadata", {})
        if metadata.get("date"):
            tracked_text(book, layer, str(metadata["date"]), (w*.12, h*.95), w*.019, "mono", w*.52, ink, align="left")
        if metadata.get("year"):
            tracked_text(book, layer, str(metadata["year"]), (w*.88, h*.95), w*.019, "mono", w*.22, ink, align="right")
    elif kind == "D2":
        tracked_text(book, layer, title, (w*.5, h*.835), w*.043, "serif", w*.76, ink, 1.5)
        tracked_text(book, layer, subtitle, (w*.5, h*.90), w*.022, "serif", w*.72, ink, 1.12)
    else:
        tracked_text(book, layer, title, (w*.11, h*.10), w*.050, "sans", w*.78, ink, align="left")
        if book.recipe["B"] == "B3":
            tracked_text(book, layer, subtitle, (w*.11, h*.85), w*.020, "sans", w*.25, ink, align="left")
        else:
            tracked_text(book, layer, subtitle, (w*.89, h*.90), w*.023, "sans", w*.76, ink, align="right")
        metadata = book.config.get("cover_metadata", {})
        detail = " · ".join(str(metadata[k]) for k in ["issue", "weather", "coordinates"] if metadata.get(k))
        if detail:
            tracked_text(book, layer, detail, (w*.11, h*.20), w*.019, "sans", w*.78, ink, align="left")
    if book.recipe["A"] == "A4":
        # A narrow highlight/shadow edge provides a quiet debossed/metallic impression.
        alpha = layer.getchannel("A")
        emboss = Image.new("RGBA", layer.size, mix(book.theme["cover"], "#ffffff", .24))
        emboss.putalpha(alpha.point(lambda v: round(v*.40)))
        backing = Image.new("RGBA", layer.size)
        backing.alpha_composite(emboss, (1, 1))
        backing.alpha_composite(layer)
        layer = backing
    return layer


def hero_frame(book, time, paste_quad):
    w, h = book.w, book.h
    frame = book.background.copy()
    height = min(h*.76, w*.48/book.recipe["ratio"])
    width = height*book.recipe["ratio"]
    cx, cy = w*.5, h*.49
    angle = math.radians(-4+math.sin(time*.65)*.30)
    points = [(-width*.50, -height*.51), (width*.50, -height*.48),
              (width*.50, height*.49), (-width*.50, height*.52)]
    quad = [(cx+x*math.cos(angle)-y*math.sin(angle), cy+x*math.sin(angle)+y*math.cos(angle)) for x, y in points]
    shadow = Image.new("RGBA", frame.size)
    shifted = [(x+width*.055, y+height*.045) for x, y in quad]
    ImageDraw.Draw(shadow).polygon(shifted, fill=(26, 32, 32, 75))
    frame.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(3, w*.017))))
    depth = max(3, width*.018)
    edge = Image.new("RGBA", frame.size)
    draw = ImageDraw.Draw(edge)
    draw.polygon([quad[1], (quad[1][0]+depth, quad[1][1]+depth), (quad[2][0]+depth, quad[2][1]+depth), quad[2]], fill=mix(book.theme["cover"], "#000000", .22))
    draw.polygon([quad[3], quad[2], (quad[2][0]+depth, quad[2][1]+depth), (quad[3][0]+depth, quad[3][1]+depth)], fill=mix(book.theme["paper"], "#9b9380", .25))
    frame.alpha_composite(edge)
    paste_quad(frame, book.cover_at(time), quad)
    return frame
