"""Plan contiguous filename-prefix groups without reordering a user's media."""
import argparse
import json
import math
import re
import unicodedata
from pathlib import Path

CAMERA_PREFIXES = {"img", "image", "images", "dsc", "dscf", "dscn", "dcim", "pxl", "vid", "photo", "default", "screenshot"}


def photo_items(scene):
    if "photos" in scene:
        if scene.get("photo"):
            raise ValueError("Use photos for a grouped page or photo for a single image, not both.")
        items = scene["photos"]
    else:
        items = [scene["photo"]]
    if not isinstance(items, list) or not items:
        raise ValueError("Each page needs at least one source image.")
    result = [{"file": item} if isinstance(item, str) else dict(item) for item in items]
    if any(not item.get("file") for item in result):
        raise ValueError("Every photo item needs a file.")
    return result


def flatten_items(scenes):
    return [item for scene in scenes for item in photo_items(scene)]


def filename_prefix(filename):
    stem = unicodedata.normalize("NFC", Path(filename).stem).strip()
    first = re.split(r"[_\s\-—]+", stem, maxsplit=1)[0]
    if first.casefold() in CAMERA_PREFIXES or first.isdigit():
        return None
    base = re.sub(r"(?:[_\s\-—]*(?:\(\d+\)|（\d+）|\d+))$", "", stem).strip(" _-—")
    # Explicit semantic prefix wins; arbitrary common letters such as IMG never do.
    prefix = re.split(r"[_\s\-—]+", base, maxsplit=1)[0] or base
    return prefix.casefold() if prefix and prefix.casefold() not in CAMERA_PREFIXES else None


def group_consecutive(items):
    groups = []
    for index, item in enumerate(items):
        item = {"file": item} if isinstance(item, str) else dict(item)
        key = item.get("group", filename_prefix(item.get("original_name", item["file"])))
        if key and groups and groups[-1]["group_key"] == key:
            groups[-1]["photos"].append(item)
            groups[-1]["source_indices"].append(index)
        else:
            groups.append({"group_key": key, "source_indices": [index], "photos": [item]})
    return groups


def left_photo_boxes(aspects, width, height, config):
    n = len(aspects)
    supplied = config.get("photo_boxes")
    if supplied is not None:
        if len(supplied) != n:
            raise ValueError("photo_boxes must have one box for each grouped photo.")
        for box in supplied:
            x, y, w, h = box
            if not all(math.isfinite(v) for v in box) or min(x, y) < 0 or min(w, h) <= 0 or x+w > 1 or y+h > 1:
                raise ValueError("A left-page photo box lies outside the paper.")
        return supplied
    if n == 1:
        return [[.10, .085, .80, .81]]
    mode = config.get("photo_layout", "auto")
    if mode not in {"auto", "stack", "side-by-side", "grid"}:
        raise ValueError("photo_layout must be auto, stack, side-by-side or grid.")
    candidates = []
    for rows in range(1, n+1):
        cols = math.ceil(n/rows)
        if mode == "stack" and cols != 1 or mode == "side-by-side" and rows != 1:
            continue
        cellw, cellh = width*.84/cols, height*.84/rows
        total = sum(min(cellw*.90/a, cellh*.90)**2*a for a in aspects)
        score = total-(rows*cols-n)*cellw*cellh*.10
        candidates.append((score, rows, cols))
    _, rows, cols = max(candidates)
    cw, ch = .84/cols, .84/rows
    result = []
    for i, aspect in enumerate(aspects):
        row, col = divmod(i, cols)
        count = min(cols, n-row*cols)
        x = .08+(cols-count)*cw/2+col*cw+cw*.035
        y = .07+row*ch+ch*.035
        box = [x, y, cw*.93, ch*.93]
        short = min(box[2]*width, box[3]*height, box[3]*height*aspect, box[2]*width/aspect)
        if short < min(width, height)*.12:
            raise ValueError("This filename-prefix group is too dense; enlarge the book or ask before splitting the group.")
        result.append(box)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="Input paths in the requested display order")
    parser.add_argument("--output", help="Save grouping plan JSON; does not edit or render media")
    args = parser.parse_args()
    plan = {"grouping": "consecutive-filename-prefix", "scenes": group_consecutive(args.files)}
    data = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(data, encoding="utf-8")
    else:
        print(data)


if __name__ == "__main__":
    main()
