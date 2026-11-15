"""Read a master book with ordered chapter files, or plan photos across folders."""
import argparse
import copy
import json
from pathlib import Path
import re

from album_inputs import filename_prefix, group_consecutive, photo_items

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".apng", ".gif", ".webp", ".tif", ".tiff", ".bmp"}


def natural_key(path):
    return [(0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in re.split(r"(\d+)", str(path))]


def scan_folders(folders, recursive=False):
    items = []
    for number, folder in enumerate(folders, 1):
        folder = Path(folder).resolve()
        if not folder.is_dir():
            raise ValueError(f"Source folder does not exist: {folder}")
        paths = folder.rglob("*") if recursive else folder.iterdir()
        paths = [path for path in paths if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
                 and not any(part.startswith(".") for part in path.relative_to(folder).parts)]
        for path in sorted(paths, key=lambda value: natural_key(value.relative_to(folder))):
            items.append({"file": str(path), "original_name": path.name, "source_folder": number})
    if not items:
        raise ValueError("The supplied folders contain no supported source images.")
    groups = group_consecutive(items)
    return {"planning_only": True, "source_folders": [str(Path(folder).resolve()) for folder in folders],
            "image_count": len(items), "scenes": groups,
            "cross_folder_groups": [i+1 for i, group in enumerate(groups)
                                    if len({item["source_folder"] for item in group["photos"]}) > 1]}


def rebase_media(item, base):
    item = {"file": item} if isinstance(item, str) else copy.deepcopy(item)
    for key in ["file", "motion_file"]:
        if item.get(key):
            item[key] = str((base/item[key]).resolve())
    return item


def boundary_key(item):
    return item.get("group", filename_prefix(item.get("original_name", item["file"])))


def load_project(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    if "parts" not in config:
        return config, []
    if config.get("scenes"):
        raise ValueError("A master project uses parts or scenes, not both.")
    entries = config["parts"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("parts must be a nonempty ordered list.")
    scenes, parts, seen = [], [], set()
    for number, entry in enumerate(entries, 1):
        entry = {"project": entry} if isinstance(entry, str) else entry
        identifier = str(entry.get("id", f"part-{number:02d}"))
        if not identifier or identifier in seen:
            raise ValueError("Every chapter needs a unique nonempty part id.")
        seen.add(identifier)
        source = (path.parent/entry["project"]).resolve()
        if source.suffix.lower() != ".json":
            raise ValueError("Parts must reference editable chapter JSON files, not completed MP4 files.")
        child = json.loads(source.read_text(encoding="utf-8"))
        extra = set(child)-{"scenes", "narrative", "metadata"}
        if extra:
            raise ValueError(f"{source.name}: move global settings {sorted(extra)} to the master project; chapters contain scenes and narrative only.")
        if not isinstance(child.get("scenes"), list) or not child["scenes"]:
            raise ValueError(f"Chapter {identifier} has no scenes.")
        start = len(scenes)+1
        for local_number, original in enumerate(child["scenes"], 1):
            scene = copy.deepcopy(original)
            if "photos" in scene:
                scene["photos"] = [rebase_media(item, source.parent) for item in scene["photos"]]
            elif "photo" in scene:
                scene["photo"] = rebase_media(scene["photo"], source.parent)
            else:
                raise ValueError(f"Chapter {identifier} page {local_number} needs source photos.")
            scene["elements"] = [rebase_media(item, source.parent) for item in scene.get("elements", [])]
            if scene.get("voiceover"):
                scene["voiceover"] = str((source.parent/scene["voiceover"]).resolve())
            scene["part_id"], scene["part_page"] = identifier, local_number
            scenes.append(scene)
        if start > 1 and not config.get("allow_boundary_group_split", False):
            previous, following = photo_items(scenes[start-2])[-1], photo_items(scenes[start-1])[0]
            key = boundary_key(previous)
            if key and key == boundary_key(following):
                raise ValueError(f"Chapter boundary splits filename group {key!r}; keep these photos in one page group, even if they live in different folders.")
        parts.append({"id": identifier, "project": str(source), "start_page": start, "end_page": len(scenes),
                      "narrative": entry.get("narrative", child.get("narrative", {}))})
    config["scenes"] = scenes
    return config, parts


def select_part(parts, value):
    if value is None:
        return None
    for part in parts:
        if part["id"] == str(value):
            return part
    if str(value).isdigit() and 1 <= int(value) <= len(parts):
        return parts[int(value)-1]
    raise ValueError("--part must identify a chapter in the master project's ordered parts list.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", nargs="+", help="Source folders in the requested story order")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    data = json.dumps(scan_folders(args.folders, args.recursive), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(data, encoding="utf-8")
    else:
        print(data)


if __name__ == "__main__":
    main()
