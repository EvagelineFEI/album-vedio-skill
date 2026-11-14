"""Source-colour art direction, tactile surfaces and editable page compositions."""
import colorsys
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageFilter, ImageOps

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def rgb(color):
    return np.asarray(ImageColor.getrgb(color)[:3], dtype=np.float32)


def hex_color(color):
    return "#" + "".join(f"{round(float(v)):02x}" for v in np.clip(color, 0, 255))


def mix(a, b, weight):
    return hex_color(rgb(a)*(1-weight) + rgb(b)*weight)


def luminance(color):
    c = rgb(color)/255
    c = np.where(c <= .04045, c/12.92, ((c+.055)/1.055)**2.4)
    return float(c @ np.array([.2126, .7152, .0722]))


def contrast(a, b):
    a, b = sorted([luminance(a), luminance(b)])
    return (b+.05)/(a+.05)


def source_palette(paths):
    samples = []
    for path in paths:
        if isinstance(path, Image.Image):
            image = path.convert("RGB")
        else:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
        # Analyse the full frame: cropping to a square would discard sky/ground colours.
        samples.append(np.asarray(image.resize((96, 96), Image.Resampling.BOX)).reshape(-1, 3))
    pixels = np.concatenate(samples)
    sheet = Image.fromarray(pixels.reshape(-1, 96, 3)).quantize(colors=10)
    palette = sheet.getpalette()
    found = []
    for count, index in sorted(sheet.getcolors(), reverse=True):
        color = palette[index*3:index*3+3]
        h, s, v = colorsys.rgb_to_hsv(*(x/255 for x in color))
        if .12 < v < .98:
            found.append({"color": hex_color(color), "weight": count/len(pixels),
                          "hue": h, "saturation": s, "value": v})
    return found or [{"color": "#787777", "weight": 1, "hue": 0,
                     "saturation": 0, "value": .47}]


def resolve_theme(paths, supplied, brief=""):
    palette = source_palette(paths)
    warm_theme = any(word in brief.lower() for word in ["金黄", "秋", "autumn", "golden"])
    candidates = [p for p in palette if .055 < p["hue"] < .18 and p["saturation"] > .12] if warm_theme else []
    candidates = candidates or palette
    accent = max(candidates, key=lambda p: math.sqrt(p["weight"])*(.25+p["saturation"])*min(p["value"], .85))["color"]
    shadow = min(palette, key=lambda p: p["value"])["color"]
    other = max(palette, key=lambda p: p["weight"]*(.35+p["saturation"]))["color"]
    theme = {"accent": accent, "cover": mix(accent, shadow, .57),
             "paper": mix(accent, "#fffdf8", .93), "ink": mix(accent, "#171714", .78),
             "background_gradient": {"colors": [mix(accent, "#f5efe6", .65),
                                                     mix(other, "#f8f2e8", .82),
                                                     mix(shadow, "#d5cbbb", .68)], "angle": 128},
             "source_palette": [p["color"] for p in palette]}
    theme.update({k: v for k, v in supplied.items() if k != "auto"})
    if "background" in supplied and "background_gradient" not in supplied:
        theme["background_gradient"] = {"colors": [mix(supplied["background"], "#ffffff", .16),
                                                       supplied["background"],
                                                       mix(supplied["background"], "#000000", .15)], "angle": 128}
    if contrast(theme["ink"], theme["paper"]) < 4.5:
        if "ink" in supplied:
            raise ValueError("Text/paper contrast is below 4.5:1; choose a readable ink colour.")
        theme["ink"] = "#302b25"
    return theme


def gradient(size, spec):
    w, h = size
    colors = spec.get("colors", [])
    if len(colors) < 2:
        raise ValueError("A background gradient needs at least two colours.")
    angle = math.radians(float(spec.get("angle", 128)))
    yy, xx = np.mgrid[:h, :w].astype(np.float32)
    field = xx/max(w-1, 1)*math.cos(angle) + yy/max(h-1, 1)*math.sin(angle)
    field = (field-field.min()) / max(float(np.ptp(field)), .001)
    # Smooth colour interpolation, with a subtle ambient highlight rather than flat bands.
    knots = np.linspace(0, 1, len(colors))
    channels = np.asarray([rgb(c) for c in colors])
    out = np.stack([np.interp(field, knots, channels[:, i]) for i in range(3)], axis=2)
    glow = np.maximum(0, 1 - ((xx/w-.48)**2 + (yy/h-.40)**2)*1.7)
    out += glow[:, :, None]*3
    noise = np.random.default_rng(29).normal(0, .30, (h, w, 1))
    return Image.fromarray(np.uint8(np.clip(out+noise, 0, 255))).convert("RGBA")


def material(size, color, kind, settings, path_resolver, side="right", seed=5):
    w, h = size
    texture_key = "paper_texture" if kind == "paper" else "cover_texture"
    default = "paper-fibers.png" if kind == "paper" else "linen-weave.png"
    path = path_resolver(settings[texture_key]) if settings.get(texture_key) else ASSETS/default
    strength = float(settings.get(kind+"_strength", .9))
    if not 0 <= strength <= 2:
        raise ValueError("Material strength must be between 0 and 2.")
    if path.is_file():
        with Image.open(path) as image:
            texture = ImageOps.fit(image.convert("L"), (w, h), method=Image.Resampling.LANCZOS)
        field = np.asarray(texture, np.float32)
        field = np.clip((field-field.mean())/max(float(field.std()), 1), -3, 3)
    elif strength:
        raise ValueError(f"Missing bundled material texture: {path}")
    else:
        field = np.zeros((h, w), np.float32)
    rng = np.random.default_rng(seed)
    detail = field*(2.9 if kind == "paper" else 4.3)*strength
    detail += rng.normal(0, .32, (h, w))*strength
    x = np.arange(w)/w
    if kind == "paper":
        detail -= np.exp(-(x if side == "right" else 1-x)/.035)[None, :]*28
        detail -= (np.abs(x-.5)*1.2)[None, :]
    else:
        detail -= np.exp(-x/.045)[None, :]*14
    out = rgb(color)[None, None, :] + detail[:, :, None]
    return Image.fromarray(np.uint8(np.clip(out, 0, 255))).convert("RGBA")


def grid_region(box, n):
    x, y, w, h = box
    if n == 1:
        return [{"box": [x+w*.08, y+h*.03, w*.84, h*.94], "rotation": -1}]
    columns = 2 if n <= 4 else 3
    rows = math.ceil(n/columns)
    cw, ch = w/columns, h/rows
    return [{"box": [x+(i%columns)*cw+cw*.07, y+(i//columns)*ch+ch*.07, cw*.86, ch*.86],
             "rotation": [-2.0, 2.0, 1.0, -1.5, 1.5, -1.0][i]} for i in range(n)]


def hero_region(box, n):
    if n <= 1 or n >= 5:
        return grid_region(box, n)
    x, y, w, h = box
    main = {"box": [x, y+.03*h, w*.53, h*.94], "rotation": -1.4}
    rest = grid_region([x+w*.60, y, w*.40, h], n-1)
    if n <= 3:
        rest = [{"box": [x+w*.63, y+i*h/(n-1)+h*.05/(n-1), w*.34, h*.85/(n-1)],
                 "rotation": 1.5 if i % 2 == 0 else -2} for i in range(n-1)]
    return [main]+rest


FAMILIES = ["caption-top", "caption-left", "caption-center", "diagonal-notes", "caption-right", "caption-bottom"]


def page_composition(config, n, number, caption_length):
    requested = config.get("layout", "auto")
    if requested == "auto":
        # Deterministic editorial rhythm; long text gets a full-width reading area.
        names = ["caption-top", "diagonal-notes", "caption-bottom"] if caption_length > 30 else FAMILIES
        requested = names[(number-1) % len(names)]
    if requested not in FAMILIES:
        raise ValueError(f"Unknown page layout {requested}; use a known family plus composition overrides.")
    if requested == "caption-top":
        text, region = [.10, .08, .80, .24], [.10, .38, .80, .54]
        elements = hero_region(region, n)
    elif requested in {"caption-left", "caption-right"}:
        left = requested == "caption-left"
        text = [.08 if left else .57, .14, .35, .71]
        region = [.51 if left else .08, .08, .41, .84]
        elements = grid_region(region, n) if n >= 4 else [
            {"box": [region[0], region[1]+i*region[3]/n, region[2], region[3]/n*.89], "rotation": [-1.5, 2, -1][i]}
            for i in range(n)]
    elif requested == "caption-center":
        text = [.12, .40, .76, .22]
        ntop = math.ceil(n/2)
        elements = grid_region([.10, .07, .80, .28], ntop)
        if n-ntop:
            elements += grid_region([.10, .68, .80, .25], n-ntop)
    elif requested == "diagonal-notes":
        text = [.51, .08, .39, .29]
        elements = [{"box": [.08, .13, .37, .64], "rotation": -2.5}]
        if n > 1:
            elements += grid_region([.51, .44, .39, .47], n-1)
    else:
        text, region = [.10, .69, .80, .24], [.10, .07, .80, .53]
        elements = hero_region(region, n)
    layout = {"family": requested, "text": {"box": text, "rotation": -1.0 if requested == "diagonal-notes" else 0,
                                              "align": "left"}, "elements": elements,
              "decorations": []}
    overrides = config.get("composition", {})
    if "text" in overrides:
        layout["text"].update(overrides["text"])
    for key in ["elements", "decorations", "allow_element_overlap"]:
        if key in overrides:
            layout[key] = overrides[key]
    validate_composition(layout, n)
    return layout


def intersection(a, b):
    x, y, w, h = a
    u, v, s, t = b
    return max(0, min(x+w, u+s)-max(x, u))*max(0, min(y+h, v+t)-max(y, v))


def validate_composition(layout, n):
    if len(layout["elements"]) != n:
        raise ValueError("Composition must specify one element box for every cutout, in source order.")
    boxes = [layout["text"]["box"]] + [e["box"] for e in layout["elements"]]
    for box in boxes:
        if len(box) != 4 or not all(math.isfinite(v) for v in box):
            raise ValueError("Boxes must contain four finite normalized numbers.")
        x, y, w, h = box
        if min(x, y) < 0 or min(w, h) <= 0 or x+w > 1.0001 or y+h > 1.0001:
            raise ValueError(f"Composition box outside the paper: {box}")
    for element in boxes[1:]:
        if intersection(boxes[0], element) > .00001:
            raise ValueError("An element overlaps the reserved handwriting area.")
    if not layout.get("allow_element_overlap", False):
        for i, a in enumerate(boxes[1:]):
            for b in boxes[i+2:]:
                if intersection(a, b) > .00001:
                    raise ValueError("Element boxes overlap; adjust composition or explicitly allow cutout layering.")
