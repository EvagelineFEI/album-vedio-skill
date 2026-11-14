"""Timed image frames and optional paired motion clips; never silently flatten animation."""
import bisect
from collections import OrderedDict
import math
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v", ".webm", ".mkv"}


class MediaSource:
    def __init__(self, item, resolver, max_size, encoder=None):
        self.item = {"file": item} if isinstance(item, str) else dict(item)
        self.path = resolver(self.item.get("motion_file") or self.item["file"])
        self.max_size = tuple(max(2, round(v)) for v in max_size)
        self.offset = float(self.item.get("offset", 0))
        self.playback = self.item.get("playback", "loop")
        if self.playback not in {"loop", "source", "once"} or not math.isfinite(self.offset) or self.offset < 0:
            raise ValueError("Media playback must be loop/source/once and offset must be nonnegative.")
        self.cache, self.video_frames = OrderedDict(), None
        self.image, self.temporary = None, None
        self.original_loop = None
        if self.path.suffix.lower() in VIDEO_SUFFIXES:
            self._decode_video(encoder)
        else:
            if self.path.suffix.lower() in {".jpg", ".jpeg"} and not self.item.get("motion_file"):
                with self.path.open("rb") as stream:
                    header = stream.read(65536)
                if re.search(rb'(?:MotionPhoto|MicroVideo)\s*=\s*["\x27]1', header):
                    raise ValueError("Motion Photo detected: supply its extracted motion_file instead of flattening the JPEG.")
            try:
                self.image = Image.open(self.path)
            except OSError as e:
                raise ValueError(f"Cannot decode {self.path.name}; supply a supported animation or its original motion clip.") from e
            self.format = self.image.format
            self.original_loop = self.image.info.get("loop")
            first = 1 if self.image.info.get("default_image", False) else 0
            self.indices = list(range(first, getattr(self.image, "n_frames", 1)))
            if not self.indices:
                raise ValueError("Animated source has no playable frames.")
            self.durations = []
            for i in self.indices:
                self.image.seek(i)
                self.image.load()
                self.durations.append(max(.01, float(self.image.info.get("duration", 100) or 100)/1000))
            self.image.seek(self.indices[0])
        self.ends, total = [], 0.0
        for duration in self.durations:
            total += duration
            self.ends.append(total)
        self.duration = total
        self.animated = len(self.indices) > 1

    def _decode_video(self, encoder):
        if encoder is None:
            raise ValueError("Paired MOV/MP4 motion needs FFmpeg.")
        self.temporary = tempfile.TemporaryDirectory(prefix="photobook-motion-")
        target = str(Path(self.temporary.name)/"%07d.png")
        width, height = self.max_size
        result = subprocess.run([encoder(), "-hide_banner", "-nostdin", "-i", str(self.path), "-an",
                                 "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,showinfo",
                                 "-fps_mode", "passthrough", target], capture_output=True, text=True, check=True)
        times = [float(t) for t in re.findall(r"pts_time:([\d.\-e+]+)", result.stderr)]
        self.video_frames = sorted(Path(self.temporary.name).glob("*.png"))
        if not self.video_frames or len(times) != len(self.video_frames):
            raise ValueError("Could not preserve motion timestamps during decoding.")
        self.indices = list(range(len(times)))
        durations = [max(.001, b-a) for a, b in zip(times, times[1:])]
        match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        total = sum(float(v)*scale for v, scale in zip(match.groups(), [3600, 60, 1])) if match else None
        tail = max(.001, total-times[-1]) if total and total > times[-1] else durations[-1] if durations else 1/30
        self.durations = durations+[tail]
        self.format = "VIDEO"

    def index_at(self, time):
        time = max(0, float(time))+self.offset
        if not self.animated:
            return 0
        if self.playback == "loop":
            time %= self.duration
        elif self.playback == "source":
            repeats = 1 if self.original_loop is None else (0 if self.original_loop == 0 else self.original_loop+(1 if self.format == "GIF" else 0))
            if repeats == 0:
                time %= self.duration
            elif time >= self.duration*repeats:
                return len(self.indices)-1
            else:
                time %= self.duration
        elif time >= self.duration:
            return len(self.indices)-1
        return min(len(self.indices)-1, bisect.bisect_right(self.ends, time))

    def frame(self, time):
        i = self.index_at(time)
        if i not in self.cache:
            if self.video_frames is not None:
                with Image.open(self.video_frames[i]) as image:
                    frame = image.convert("RGBA")
            else:
                self.image.seek(self.indices[i])
                # Pillow supplies composed GIF/APNG/WebP frames, including disposal/blending.
                frame = ImageOps.exif_transpose(self.image.convert("RGBA"))
            frame = ImageOps.contain(frame, self.max_size, Image.Resampling.LANCZOS)
            self.cache[i] = frame.copy()
            if len(self.cache) > 12:
                self.cache.popitem(last=False)
        self.cache.move_to_end(i)
        return self.cache[i].copy()

    def info(self):
        return {"file": self.item["file"], "original_name": self.item.get("original_name"), "motion_file": self.item.get("motion_file"),
                "format": self.format, "animated": self.animated, "frames": len(self.indices),
                "duration": self.duration if self.animated else None, "frame_durations": self.durations if self.animated else [],
                "playback": self.playback, "original_loop": self.original_loop}

    def __del__(self):
        if getattr(self, "image", None) is not None:
            self.image.close()
        if getattr(self, "temporary", None) is not None:
            self.temporary.cleanup()
