import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

SAMPLES = 4


def sample_frames(path: Path, kind: str, duration_ms: int | None, n: int = SAMPLES) -> list[Image.Image]:
    """Evenly spaced RGB frames for embedding. Stills give one; animations and videos give up to n."""
    if kind == "video":
        return _video_frames(path, duration_ms, n)
    out = []
    with Image.open(path) as img:
        total = getattr(img, "n_frames", 1)
        picks = sorted({round(i * (total - 1) / max(1, n - 1)) for i in range(n)}) if total > 1 else [0]
        for i in picks:
            img.seek(i)
            frame = ImageOps.exif_transpose(img.convert("RGBA"))
            bg = Image.new("RGBA", frame.size, (255, 255, 255, 255))  # flatten transparency on white
            out.append(Image.alpha_composite(bg, frame).convert("RGB"))
    return out


def _video_frames(path: Path, duration_ms: int | None, n: int) -> list[Image.Image]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for video frames")
    length = (duration_ms or 0) / 1000
    times = [length * (i + 0.5) / n for i in range(n)] if length > 0 else [0.0]
    frames = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            png = Path(tmp) / f"{i}.png"
            subprocess.run(
                [ffmpeg, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", str(png)],
                timeout=60, check=False,
            )
            if png.exists():
                with Image.open(png) as im:
                    frames.append(im.convert("RGB"))
    if not frames:
        raise RuntimeError("could not decode any video frame")
    return frames
