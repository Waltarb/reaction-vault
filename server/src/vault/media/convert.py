"""MP4 and GIF renditions via ffmpeg. Animated images are decoded with Pillow first, because
ffmpeg's decoder support for animated WebP is unreliable."""
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

MAX_WIDTH_MP4 = 720
MAX_WIDTH_GIF = 480
GIF_FPS = 15
MAX_SECONDS = 10
MAX_FRAMES = 300


class ConvertError(Exception):
    pass


def ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise ConvertError("ffmpeg is not installed")
    return path


def _write_frames(src: Path, out_dir: Path) -> float:
    """Dump an animated image as flattened PNGs. Returns the average fps."""
    with Image.open(src) as img:
        total = getattr(img, "n_frames", 1)
        step = max(1, -(-total // MAX_FRAMES))
        picks = list(range(0, total, step))
        elapsed_ms = 0
        for n, i in enumerate(picks):
            img.seek(i)
            frame = img.convert("RGBA")
            bg = Image.new("RGBA", frame.size, (255, 255, 255, 255))
            Image.alpha_composite(bg, frame).convert("RGB").save(out_dir / f"{n:05d}.png")
            elapsed_ms += int(img.info.get("duration", 100) or 100) * step
    seconds = max(elapsed_ms / 1000, 0.04)
    return min(max(len(picks) / seconds, 1.0), 30.0)


def _run(args: list[str]) -> None:
    proc = subprocess.run(
        [ffmpeg_path(), "-v", "error", "-y", *args], capture_output=True, text=True, timeout=300
    )
    if proc.returncode != 0:
        raise ConvertError(proc.stderr.strip()[-500:] or "ffmpeg failed")


def _convert(src: Path, dest: Path, kind: str, out_args) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = dest.with_name(dest.stem + ".tmp" + dest.suffix)
    with tempfile.TemporaryDirectory() as tmp:
        if kind == "video":
            inputs = ["-t", str(MAX_SECONDS), "-i", str(src)]
        else:
            fps = _write_frames(src, Path(tmp))
            inputs = ["-framerate", f"{fps:.3f}", "-i", str(Path(tmp) / "%05d.png")]
        try:
            _run([*inputs, *out_args, str(tmp_out)])
            tmp_out.replace(dest)
        finally:
            tmp_out.unlink(missing_ok=True)


def to_mp4(src: Path, dest: Path, kind: str) -> None:
    scale = f"scale='trunc(min(iw,{MAX_WIDTH_MP4})/2)*2':'trunc(ow/a/2)*2'"
    _convert(
        src, dest, kind,
        ["-an", "-vf", scale, "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
    )


def to_gif(src: Path, dest: Path, kind: str) -> None:
    vf = (
        f"fps={GIF_FPS},scale='min(iw,{MAX_WIDTH_GIF})':-1:flags=lanczos,"
        "split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5"
    )
    _convert(src, dest, kind, ["-an", "-vf", vf, "-loop", "0"])
