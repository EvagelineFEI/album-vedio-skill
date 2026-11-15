"""Content-addressed video segments and a separate continuous soundtrack."""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np
import PIL
from PIL import ImageFont

CACHE_VERSION = 1
SCRIPTS = Path(__file__).resolve().parent
VIDEO_OPTIONS = ["-c:v", "libx264", "-preset", "medium", "-crf", "19",
                 "-pix_fmt", "yuv420p", "-bf", "0", "-sc_threshold", "0"]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            value.update(block)
    return value.hexdigest()


def image_digest(image):
    return digest([image.mode, image.size, hashlib.sha256(image.tobytes()).hexdigest()])


def parse_pages(text, count):
    try:
        pages = {int(part.strip()) for part in text.split(",")} if text.strip() else set()
    except ValueError as error:
        raise ValueError("--rebuild-pages needs comma-separated page numbers, e.g. 2,4.") from error
    if any(page < 1 or page > count for page in pages):
        raise ValueError(f"Page numbers must be between 1 and {count}.")
    return pages


def valid_cache(path, key):
    try:
        info = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        return (info["key"] == key and info["bytes"] > 0
                and path.stat().st_size == info["bytes"] and file_digest(path) == info["sha256"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def publish_cache(source, destination, key, **details):
    info = {"key": key, "bytes": source.stat().st_size, "sha256": file_digest(source), **details}
    metadata = source.with_suffix(".json")
    metadata.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    source.replace(destination)
    metadata.replace(destination.with_suffix(".json"))


@dataclass
class Segment:
    id: str
    kind: str
    index: int | None
    pages: list
    start_frame: int
    frames: int
    key: str
    path: Path
    reused: bool
    reason: str

    def info(self):
        return {"id": self.id, "kind": self.kind, "pages": self.pages,
                "start_frame": self.start_frame, "frames": self.frames, "key": self.key,
                "file": str(self.path), "action": "reuse" if self.reused else "render", "reason": self.reason}


@dataclass
class CachePlan:
    directory: Path
    segments: list
    audio_path: Path
    audio_key: str
    audio_reused: bool

    def report(self):
        return {"mode": "incremental", "cache_dir": str(self.directory),
                "video_assembly": "stream-copy",
                "rendered_segments": [job.id for job in self.segments if not job.reused],
                "reused_segments": [job.id for job in self.segments if job.reused],
                "rendered_frames": sum(job.frames for job in self.segments if not job.reused),
                "reused_frames": sum(job.frames for job in self.segments if job.reused),
                "audio_reused": self.audio_reused, "segments": [job.info() for job in self.segments]}


def cache_plan(book, encoder, cache_dir=None, rebuild_pages=(), rebuild_all=False, rate=44100):
    """Fingerprint resolved visual dependencies, never the whole project or absolute start time."""
    if any(page < 1 or page > len(book.scenes) for page in rebuild_pages):
        raise ValueError("A requested rebuild page does not exist.")
    directory = Path(cache_dir).resolve() if cache_dir else book.path.parent/".album-cache"/book.path.stem
    hashes = {}

    def asset_hash(path):
        path = Path(path).resolve()
        if path not in hashes:
            hashes[path] = file_digest(path)
        return hashes[path]

    def media(source):
        return {"file": asset_hash(book.asset(source.item["file"])),
                "motion_file": asset_hash(book.asset(source.item["motion_file"])) if source.item.get("motion_file") else None,
                "format": source.format, "size": source.max_size, "durations": source.durations,
                "playback": source.playback, "offset": source.offset, "loop": source.original_loop}

    code = {path.name: asset_hash(path) for path in sorted(SCRIPTS.glob("*.py"))}
    version = subprocess.run([encoder, "-version"], capture_output=True, text=True, check=True).stdout
    runtime = {"code": code, "python": platform.python_version(), "pillow": PIL.__version__, "numpy": np.__version__,
               "freetype": ImageFont.core.freetype2_version, "machine": platform.machine(), "encoder": version}
    common = {"version": CACHE_VERSION, "runtime": runtime,
              "size": [book.w, book.h, book.pw, book.ph], "fps": book.fps, "codec": VIDEO_OPTIONS}
    pages = []
    for scene in book.scenes:
        payload = {
            "stage": image_digest(scene.stage), "paper_left": image_digest(scene.paper_left),
            "paper_right": image_digest(scene.paper_right), "duration": scene.duration, "incoming": scene.incoming,
            "photos": [media(source) for source in scene.photo_sources], "photo_boxes": scene.photo_boxes,
            "photo_rotation": scene.config.get("photo_rotation", -1 if scene.number % 2 else 1),
            "number": scene.number, "motion": book.motion,
            "elements": [{"source": media(source), "center": sprite[1], "rotation": sprite[2], "size": size}
                         for source, sprite, size in zip(scene.sprite_sources, scene.sprites, scene.sprite_sizes)],
            "text": {"font": asset_hash(book.font_file), "size": scene.font.size, "glyphs": scene.glyphs,
                     "rect": scene.text_rect, "width_scale": scene.width_scale, "ink": scene.ink,
                     "composition": scene.composition["text"], "start": scene.caption_start, "write_time": scene.write_time},
            "element_start": scene.element_start, "element_gap": scene.gap,
        }
        pages.append(digest(payload))
    cover = {"plain": image_digest(book.cover_plain), "title": image_digest(book.cover_title),
             "media": media(book.cover_media), "recipe": book.recipe}
    jobs = []
    cursor = 0

    def add(identifier, kind, index, affected, seconds, dependencies):
        nonlocal cursor
        frames = round(seconds*book.fps)
        if not frames:
            return
        key = digest({"common": common, "kind": kind, "frames": frames, "dependencies": dependencies})
        path = directory/"video"/f"{key}.mp4"
        forced = rebuild_all or bool(set(affected).intersection(rebuild_pages))
        reused = not forced and valid_cache(path, key)
        reason = "unchanged" if reused else "forced" if forced else "cache-invalid" if path.exists() else "not-cached"
        jobs.append(Segment(identifier, kind, index, affected, cursor, frames, key, path, reused, reason))
        cursor += frames

    if book.prologue:
        intro = book.intro
        add("intro", "intro", None, [], book.prologue,
            {"cover": cover, "background": image_digest(book.background), "closed_stage": image_digest(book.closed_stage),
             "camera": image_digest(intro.camera), "config": {k: v for k, v in intro.config.items() if k != "camera_asset"},
             "timeline": intro.timeline(), "photos": [media(source) for source in intro.card_sources]})
    add("opening", "opening", 0, [1], book.opening,
        {"cover": cover, "closed_stage": image_digest(book.closed_stage), "page": pages[0]})
    for index, scene in enumerate(book.scenes):
        add(f"page-{index+1:04d}", "page", index, [index+1], scene.duration, pages[index])
        if index+1 < len(book.scenes):
            add(f"turn-{index+1:04d}-{index+2:04d}", "turn", index, [index+1, index+2], book.turn,
                [pages[index], pages[index+1]])
    add("ending", "ending", len(book.scenes)-1, [len(book.scenes)], book.final_hold, pages[-1])
    if cursor != round(book.total*book.fps):
        raise ValueError("Segment frame counts do not cover the complete book timeline.")
    music = book.config.get("music", {})
    audio_key = digest({"version": CACHE_VERSION, "runtime": runtime, "rate": rate,
                        "duration": book.total, "music": music,
                        "music_file": asset_hash(book.asset(music["file"])) if music.get("mode") == "file" else None,
                        "sfx": book.config.get("sfx", True), "shots": book.intro.shots, "opening": book.prologue,
                        "scenes": [{"start": scene.start, "duration": scene.duration, "element_start": scene.element_start,
                                    "gap": scene.gap, "elements": len(scene.sprites),
                                    "voice": hashlib.sha256(scene.voice.tobytes()).hexdigest() if scene.voice is not None else None}
                                   for scene in book.scenes]})
    audio_path = directory/"audio"/f"{audio_key}.wav"
    return CachePlan(directory, jobs, audio_path, audio_key,
                     not rebuild_all and valid_cache(audio_path, audio_key))


def encode_segment(book, job, encoder):
    job.path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".encode-", dir=job.path.parent) as temp:
        target = Path(temp)/"segment.mp4"
        command = [encoder, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                   "-s", f"{book.w}x{book.h}", "-r", str(book.fps), "-i", "pipe:0", "-an",
                   *VIDEO_OPTIONS, "-g", str(book.fps*2), "-keyint_min", str(book.fps*2),
                   "-video_track_timescale", str(book.fps*1000), "-frames:v", str(job.frames), str(target)]
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
            try:
                for index in range(job.frames):
                    frame = book.segment_frame(job.kind, job.index, index/book.fps)
                    process.stdin.write(frame.convert("RGB").tobytes())
                process.stdin.close()
                code = process.wait()
                if code:
                    errors.seek(0)
                    raise RuntimeError(errors.read().decode(errors="replace"))
            except BaseException:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except BrokenPipeError:
                        pass
                errors.seek(0)
                print(errors.read().decode(errors="replace"), file=sys.stderr)
                raise
        publish_cache(target, job.path, job.key, frames=job.frames, fps=book.fps)


def encode_audio(book, plan, mix_audio, rate):
    plan.audio_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mix-", dir=plan.audio_path.parent) as temp:
        target = Path(temp)/"audio.wav"
        audio = mix_audio(book)
        with wave.open(str(target), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes((np.clip(audio, -1, 1)*32767).astype("<i2").tobytes())
        publish_cache(target, plan.audio_path, plan.audio_key, samples=math.ceil(book.total*rate), rate=rate)


def concat_quote(path):
    text = path.as_posix()
    if any(char in text for char in "\r\n\0"):
        raise ValueError("The cache path cannot contain a newline or NUL character.")
    return "'"+text.replace("'", "'\\''")+"'"


def render_cached(book, output, overwrite, encoder, mix_audio, rate,
                  cache_dir=None, rebuild_pages=(), rebuild_all=False):
    output = Path(output).resolve()
    if output.suffix.lower() != ".mp4":
        raise ValueError("Output filename must end in .mp4.")
    if output.exists() and not overwrite:
        raise ValueError(f"Output already exists: {output}; choose a new name or --overwrite.")
    plan = cache_plan(book, encoder, cache_dir, rebuild_pages, rebuild_all, rate)
    for job in plan.segments:
        print(f"{'Reuse' if job.reused else 'Render'} {job.id} ({job.frames} frames)", file=sys.stderr, flush=True)
        if not job.reused:
            encode_segment(book, job, encoder)
    if not plan.audio_reused:
        encode_audio(book, plan, mix_audio, rate)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".book-assemble-", dir=output.parent) as temp:
        temp = Path(temp)
        listing = temp/"segments.ffconcat"
        listing.write_text("ffconcat version 1.0\n"+"".join(f"file {concat_quote(job.path)}\n" for job in plan.segments), encoding="utf-8")
        target = temp/"movie.mp4"
        command = [encoder, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                   "-i", str(plan.audio_path), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                   "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-af", "loudnorm=I=-18:TP=-1.5:LRA=7",
                   "-t", str(book.total), "-movflags", "+faststart", str(target)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        report = {"video": str(output), "duration": book.total, "scenes": len(book.scenes), **plan.report()}
        timeline = book.timeline()
        timeline["render_report"] = output.with_suffix(".render.json").name
        (temp/"timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
        (temp/"render.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        first = book.scenes[0]
        poster = book.hero_cover_frame(.2) if book.intro.mode == "cover-camera-book" else book.frame(first.start+first.caption_start+first.write_time+.3)
        poster.convert("RGB").save(temp/"cover.jpg", quality=95)
        shutil.copyfile(plan.audio_path, temp/"audio.wav")
        for source, suffix in [("timeline.json", ".timeline.json"), ("render.json", ".render.json"),
                               ("cover.jpg", ".cover.jpg"), ("audio.wav", ".audio.wav")]:
            (temp/source).replace(output.with_suffix(suffix))
        target.replace(output)
    print(json.dumps({key: report[key] for key in ["video", "duration", "rendered_segments", "reused_segments", "audio_reused"]}, ensure_ascii=False))
    return report
