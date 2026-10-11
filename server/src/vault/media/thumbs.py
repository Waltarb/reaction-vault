import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

THUMB_SIZE = 320
PREVIEW_SIZE = 480
MAX_PREVIEW_FRAMES = 90


def make_thumb(src: Path, dest: Path, kind: str) -> tuple[int, int]:
    """Write a static WebP thumbnail (first frame, longest side THUMB_SIZE). Returns its size."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if kind == "video":
        return _video_thumb(src, dest)
    with Image.open(src) as img:
        img.seek(0)
        frame = ImageOps.exif_transpose(img.convert("RGBA"))
        frame.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
        frame.save(dest, "WEBP", quality=82, method=4)
        return frame.size


def make_preview(src: Path, dest: Path) -> tuple[int, int] | None:
    """Animated WebP preview for animated images, capped in size and frame count."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as img:
        total = getattr(img, "n_frames", 1)
        if total < 2:
            return None
        step = max(1, -(-total // MAX_PREVIEW_FRAMES))
        frames, durations = [], []
        for i in range(0, total, step):
            img.seek(i)
            f = img.convert("RGBA")
            f.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.Resampling.LANCZOS)
            frames.append(f)
            durations.append(max(20, int(img.info.get("duration", 100) or 100)) * step)
        frames[0].save(
            dest, "WEBP", save_all=True, append_images=frames[1:], duration=durations,
            loop=0, quality=70, method=4,
        )
        return frames[0].size


def _video_thumb(src: Path, dest: Path) -> tuple[int, int]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for video thumbnails")
    png = dest.with_suffix(".frame.png")
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", str(src), "-frames:v", "1", str(png)],
        check=True, timeout=60,
    )
    try:
        return make_thumb(png, dest, "image")
    finally:
        png.unlink(missing_ok=True)
