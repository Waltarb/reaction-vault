import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PIXELS = 100_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class UnsupportedMedia(Exception):
    pass


@dataclass
class MediaInfo:
    kind: str  # image | animated | video
    mime: str
    width: int
    height: int
    duration_ms: int | None
    frame_count: int | None
    has_alpha: bool
    has_audio: bool
    phash: int | None

    def as_dict(self) -> dict:
        return asdict(self)


def dhash(img: Image.Image) -> int:
    """64-bit difference hash, returned as a signed int so SQLite can store it."""
    small = ImageOps.grayscale(img.convert("RGBA")).resize((9, 8), Image.Resampling.LANCZOS)
    px = list(small.tobytes())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits - (1 << 64) if bits >= (1 << 63) else bits


def hamming(a: int, b: int) -> int:
    return ((a ^ b) & ((1 << 64) - 1)).bit_count()


def _has_alpha(img: Image.Image, frames: int) -> bool:
    """True transparency, not just an alpha channel: WebP/PNG often carry a fully opaque one."""
    if img.mode == "P":
        return "transparency" in img.info
    if img.mode not in ("RGBA", "LA", "PA"):
        return "transparency" in img.info
    for i in sorted({0, frames // 2, frames - 1}):
        img.seek(i)
        if img.convert("RGBA").getchannel("A").getextrema()[0] < 255:
            return True
    return False


def _probe_image(path: Path) -> MediaInfo:
    with Image.open(path) as img:
        fmt = img.format
        mime = Image.MIME.get(fmt or "")
        if not mime:
            raise UnsupportedMedia(f"unsupported image format: {fmt}")
        frames = getattr(img, "n_frames", 1)
        duration = None
        if frames > 1:
            total = 0
            for i in range(frames):
                img.seek(i)
                total += int(img.info.get("duration", 0) or 0)
            img.seek(0)
            duration = total or None
        has_alpha = _has_alpha(img, frames)
        img.seek(0)
        first = ImageOps.exif_transpose(img.copy())
        width, height = first.size
        return MediaInfo(
            kind="animated" if frames > 1 else "image",
            mime=mime,
            width=width,
            height=height,
            duration_ms=duration,
            frame_count=frames,
            has_alpha=bool(has_alpha),
            has_audio=False,
            phash=dhash(first),
        )


def _probe_video(path: Path) -> MediaInfo:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise UnsupportedMedia("not an image and ffprobe is not available")
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise UnsupportedMedia("unrecognised file")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise UnsupportedMedia("no video stream")
    names = data.get("format", {}).get("format_name", "")
    if "webm" in names or "matroska" in names:
        mime = "video/webm"
    elif "mp4" in names or "mov" in names:
        mime = "video/mp4"
    else:
        raise UnsupportedMedia(f"unsupported container: {names}")
    duration = data.get("format", {}).get("duration")
    pix_fmt = video.get("pix_fmt", "")
    return MediaInfo(
        kind="video",
        mime=mime,
        width=int(video["width"]),
        height=int(video["height"]),
        duration_ms=int(float(duration) * 1000) if duration else None,
        frame_count=int(video["nb_frames"]) if str(video.get("nb_frames", "")).isdigit() else None,
        has_alpha=pix_fmt.startswith(("yuva", "rgba", "bgra", "argb", "abgr", "gbrap")),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        phash=None,
    )


def probe(path: Path) -> MediaInfo:
    """Identify a file by content, never by its name or the client's content type."""
    try:
        return _probe_image(path)
    except (UnidentifiedImageError, OSError, SyntaxError):
        pass
    except Image.DecompressionBombError as e:
        raise UnsupportedMedia("image too large") from e
    return _probe_video(path)
