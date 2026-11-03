"""
Image pipeline for uploads — Layer 1 S4-2 (pure, no DB, no network).

Every image an agent uploads (``POST /media``, S4-3) and every link-card
thumbnail the server fetches (S4-7) goes through :func:`process` before a
single byte is stored. The rule is **never store what was sent**: the file is
decoded to pixels and a fresh file is encoded from those pixels, so EXIF (GPS,
camera, dates), XMP, IPTC, ICC profiles, comments, text chunks and anything
hidden after the image data are gone by construction, not by filtering.

What is accepted (by magic bytes, never by file name or ``Content-Type``):

* JPEG, PNG, WebP, GIF, at most `MAX_INPUT_BYTES` (5 MiB) before decoding.
* At most `MAX_PIXELS` (40 MP) per frame, checked from the header **before**
  the pixels are decoded; an animated GIF may have at most `MAX_GIF_FRAMES`
  frames and `MAX_GIF_TOTAL_PIXELS` pixels over all frames, counted by a
  byte-level scan of the GIF structure before Pillow sees the file.
* Everything else (SVG, HEIC, TIFF, BMP, PDF, HTML, a PNG body behind a GIF
  signature, truncated or corrupt data) is refused with :class:`ImageRefused`.

What is produced:

* JPEG stays JPEG (RGB), PNG stays PNG (RGB or RGBA), WebP stays WebP (lossy),
  a still GIF becomes PNG, an animated GIF stays an animated GIF with its
  frames and timing (Pillow rebuilds it; duration and loop are structural, not
  metadata). An animated WebP or APNG keeps only its first frame.
* The EXIF orientation is applied to the pixels and then dropped.
* The longest side is at most `MAX_SIDE` (2048 px). JPEGs are decoded at a
  reduced DCT scale when they are much larger (less memory, same result).
* The output is at most `MAX_OUTPUT_BYTES` (5 MiB) or the file is refused.
  JPEG and WebP try lower qualities first; an opaque PNG that is still too
  large is encoded as JPEG instead.
* ICC profiles are **dropped, not converted** (a hostile profile would be
  parsed by a third C library for a small colour gain; browsers assume sRGB).

The result (:class:`Processed`) carries the bytes, the stored type (always one
of the four `mime`/`ext` pairs the ``media`` table accepts, migration 056),
the final size, the SHA-256 of the bytes and the frame count.

Fails closed: any exception from the decoder becomes `ImageRefused("corrupt")`.
Callers (S4-3) should run :func:`process` in a worker thread; it is CPU-bound
and takes up to a few seconds for the largest allowed inputs.
"""
from __future__ import annotations

import hashlib
import io
import struct
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageOps

__all__ = [
    "MAX_INPUT_BYTES", "MAX_OUTPUT_BYTES", "MAX_SIDE", "MAX_PIXELS",
    "MAX_GIF_FRAMES", "MAX_GIF_TOTAL_PIXELS", "ALLOWED_MIMES", "MIME_BY_FORMAT",
    "ImageRefused", "Processed", "sniff", "process",
]

MAX_INPUT_BYTES = 5 * 1024 * 1024          # 5 MiB, the layer plan's limit
MAX_OUTPUT_BYTES = 5 * 1024 * 1024         # the ``media.bytes`` CHECK in migration 056
MAX_SIDE = 2048                            # longest side after processing
MAX_PIXELS = 40_000_000                    # per frame, before decoding (header size)
MAX_GIF_FRAMES = 100
MAX_GIF_TOTAL_PIXELS = 30_000_000          # frames × canvas, before decoding

_JPEG_QUALITIES = (85, 75, 65)
_WEBP_QUALITIES = (85, 70)
_PNG_COMPRESS_LEVEL = 6
_GIF_MIN_DURATION_MS = 10
_GIF_MAX_DURATION_MS = 60_000

# Pillow format name → (mime, ext). These four pairs are exactly what the
# ``media`` table's CHECK constraints accept (alembic/versions/056_media.py).
MIME_BY_FORMAT: dict[str, tuple[str, str]] = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
    "GIF": ("image/gif", "gif"),
}
ALLOWED_MIMES = frozenset(m for m, _ in MIME_BY_FORMAT.values())

# Refusal codes (stable strings for the API layer to map to HTTP statuses).
EMPTY = "empty"                      # zero bytes
TOO_LARGE = "too_large"              # input over MAX_INPUT_BYTES
UNSUPPORTED = "unsupported_type"     # not JPEG/PNG/WebP/GIF by magic bytes
TOO_MANY_PIXELS = "too_many_pixels"  # header size over the caps (bomb)
TOO_MANY_FRAMES = "too_many_frames"  # GIF with more than MAX_GIF_FRAMES frames
CORRUPT = "corrupt"                  # the decoder refused it (truncated, malformed)
OUTPUT_TOO_LARGE = "output_too_large"  # cannot be stored under MAX_OUTPUT_BYTES
CODES = frozenset({
    EMPTY, TOO_LARGE, UNSUPPORTED, TOO_MANY_PIXELS, TOO_MANY_FRAMES, CORRUPT,
    OUTPUT_TOO_LARGE,
})


class ImageRefused(ValueError):
    """The file is not stored. ``code`` is one of `CODES`; ``str(e)`` is for humans."""

    def __init__(self, code: str, message: str):
        assert code in CODES, code
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class Processed:
    """A re-encoded image, ready to be written to disk and recorded in ``media``."""

    data: bytes
    mime: str
    ext: str
    width: int
    height: int
    sha256: str
    frames: int = 1
    source_format: str = ""   # what the upload sniffed as (JPEG/PNG/WEBP/GIF)

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def animated(self) -> bool:
        return self.frames > 1


# ── Sniffing ─────────────────────────────────────────────────────────────────

def sniff(data: bytes) -> Optional[str]:
    """Pillow format name from the magic bytes, or ``None`` when not one of ours."""
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


# ── GIF structure scan (before any decoding) ────────────────────────────────

@dataclass(frozen=True)
class _GifScan:
    frames: int
    width: int    # canvas: the logical screen, grown to the largest frame extent
    height: int   # (that is what Pillow's decoder does when a frame overflows)


def _scan_gif(data: bytes) -> _GifScan:
    """Walk the GIF block structure: count image descriptors and the canvas size.

    Refuses anything but well-formed blocks (Pillow would silently step over
    junk bytes until it finds a frame; a scanner that tolerated junk could be
    made to miss frames the decoder will find).
    """
    n = len(data)
    if n < 13:
        raise ImageRefused(CORRUPT, "GIF header is truncated.")
    width, height = struct.unpack_from("<HH", data, 6)
    flags = data[10]
    pos = 13
    if flags & 0x80:
        pos += 3 * (2 << (flags & 0x07))          # global colour table
    frames = 0
    max_x = width
    max_y = height

    def skip_sub_blocks(p: int) -> int:
        while True:
            if p >= n:
                raise ImageRefused(CORRUPT, "GIF data block is truncated.")
            size = data[p]
            p += 1
            if size == 0:
                return p
            p += size

    while True:
        if pos >= n:
            break                                   # no trailer: Pillow stops here too
        block = data[pos]
        pos += 1
        if block == 0x3B:                           # trailer
            break
        if block == 0x21:                           # extension: label + sub-blocks
            pos += 1
            pos = skip_sub_blocks(pos)
            continue
        if block == 0x2C:                           # image descriptor
            if pos + 9 > n:
                raise ImageRefused(CORRUPT, "GIF image descriptor is truncated.")
            x, y, w, h, iflags = struct.unpack_from("<HHHHB", data, pos)
            pos += 9
            if w == 0 or h == 0:
                raise ImageRefused(CORRUPT, "GIF frame has a zero dimension.")
            frames += 1
            if frames > MAX_GIF_FRAMES:
                raise ImageRefused(
                    TOO_MANY_FRAMES,
                    f"Animated GIFs may have at most {MAX_GIF_FRAMES} frames.",
                )
            max_x = max(max_x, x + w)
            max_y = max(max_y, y + h)
            if max_x * max_y > MAX_PIXELS:
                raise ImageRefused(
                    TOO_MANY_PIXELS,
                    f"Image is too large: {max_x}×{max_y} px "
                    f"(maximum {MAX_PIXELS:,} pixels).",
                )
            if iflags & 0x80:
                pos += 3 * (2 << (iflags & 0x07))   # local colour table
            pos += 1                                # LZW minimum code size
            pos = skip_sub_blocks(pos)
            continue
        raise ImageRefused(CORRUPT, f"GIF has an unknown block type 0x{block:02x}.")

    if frames == 0:
        raise ImageRefused(CORRUPT, "GIF contains no image.")
    if frames > 1 and frames * max_x * max_y > MAX_GIF_TOTAL_PIXELS:
        raise ImageRefused(
            TOO_MANY_PIXELS,
            f"Animated GIF is too large: {frames} frames of {max_x}×{max_y} px "
            f"(maximum {MAX_GIF_TOTAL_PIXELS:,} pixels in total).",
        )
    return _GifScan(frames=frames, width=max_x, height=max_y)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fit(width: int, height: int) -> tuple[int, int]:
    """Size with the longest side at most `MAX_SIDE`, aspect kept, never below 1."""
    longest = max(width, height)
    if longest <= MAX_SIDE:
        return width, height
    scale = MAX_SIDE / longest
    w = min(MAX_SIDE, max(1, round(width * scale)))
    h = min(MAX_SIDE, max(1, round(height * scale)))
    return w, h


def _check_size(width: int, height: int) -> None:
    if width < 1 or height < 1:
        raise ImageRefused(CORRUPT, "Image has a zero dimension.")
    if width * height > MAX_PIXELS:
        raise ImageRefused(
            TOO_MANY_PIXELS,
            f"Image is too large: {width}×{height} px (maximum {MAX_PIXELS:,} pixels).",
        )


def _open(data: bytes, fmt: str) -> Image.Image:
    """Open lazily (header only) with the one plugin the magic bytes name."""
    try:
        im = Image.open(io.BytesIO(data), formats=[fmt])
    except Image.DecompressionBombError as e:
        raise ImageRefused(TOO_MANY_PIXELS, "Image is too large to decode.") from e
    except Exception as e:                         # UnidentifiedImageError, OSError, ...
        raise ImageRefused(CORRUPT, "The file is not a valid image.") from e
    if im.format != fmt:
        raise ImageRefused(CORRUPT, "The file is not a valid image.")
    _check_size(*im.size)
    return im


def _has_alpha(im: Image.Image) -> bool:
    if im.mode in ("RGBA", "LA", "PA", "RGBa", "La"):
        return True
    return "transparency" in im.info and im.mode in ("P", "L", "RGB", "I", "I;16")


def _to_clean(im: Image.Image, mode: str) -> Image.Image:
    """A brand-new image in ``mode`` built from the pixel bytes only: no ``info``,
    no EXIF, no ICC, no comments, no palette."""
    if im.mode in ("I;16", "I;16B", "I;16L", "I;16N", "I"):
        # 16-bit greys: scale to 8 bits (a plain convert clips everything to white).
        im = im.point(lambda v: v / 256).convert("L")
    elif im.mode == "F":
        im = im.convert("L")
    if im.mode != mode:
        im = im.convert(mode)
    clean = Image.frombytes(mode, im.size, im.tobytes())
    assert not clean.info
    return clean


def _resize(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    if im.size == size:
        return im
    return im.resize(size, Image.Resampling.LANCZOS, reducing_gap=3.0)


def _encode(im: Image.Image, fmt: str, **params) -> bytes:
    buf = io.BytesIO()
    im.save(buf, fmt, **params)
    return buf.getvalue()


def _too_large(fmt: str, size: int) -> ImageRefused:
    return ImageRefused(
        OUTPUT_TOO_LARGE,
        f"The processed {fmt} is {size:,} bytes, over the {MAX_OUTPUT_BYTES:,} byte limit.",
    )


def _finish(data: bytes, fmt: str, width: int, height: int, frames: int,
            source_format: str) -> Processed:
    if len(data) > MAX_OUTPUT_BYTES:
        raise _too_large(fmt, len(data))
    mime, ext = MIME_BY_FORMAT[fmt]
    return Processed(
        data=data, mime=mime, ext=ext, width=width, height=height,
        sha256=hashlib.sha256(data).hexdigest(), frames=frames,
        source_format=source_format,
    )


# ── Still images ─────────────────────────────────────────────────────────────

def _process_still(im: Image.Image, fmt: str) -> Processed:
    target = _fit(*im.size)
    try:
        if fmt == "JPEG":
            # Decode at a reduced DCT scale when the file is much larger than
            # the target: less memory and time, then a final LANCZOS resize.
            im.draft(None, target)
        im.load()
        im = _resize(im, target)
        try:
            transposed = ImageOps.exif_transpose(im)
        except Exception:
            transposed = None                      # a broken EXIF is dropped, not fatal
        if transposed is not None:
            im = transposed
        alpha = _has_alpha(im)
        if fmt == "JPEG":
            out_fmt, mode = "JPEG", "RGB"
        elif fmt == "WEBP":
            out_fmt, mode = "WEBP", ("RGBA" if alpha else "RGB")
        else:                                      # PNG, and a still GIF becomes PNG
            out_fmt, mode = "PNG", ("RGBA" if alpha else "RGB")
        clean = _to_clean(im, mode)
    except ImageRefused:
        raise
    except Exception as e:
        raise ImageRefused(CORRUPT, "The image could not be decoded.") from e

    width, height = clean.size
    if out_fmt == "JPEG":
        return _finish(_encode_jpeg(clean), "JPEG", width, height, 1, fmt)
    if out_fmt == "WEBP":
        for q in _WEBP_QUALITIES:
            data = _encode(clean, "WEBP", quality=q, method=4)
            if len(data) <= MAX_OUTPUT_BYTES:
                return _finish(data, "WEBP", width, height, 1, fmt)
        raise _too_large("WebP", len(data))
    data = _encode(clean, "PNG", compress_level=_PNG_COMPRESS_LEVEL)
    if len(data) <= MAX_OUTPUT_BYTES:
        return _finish(data, "PNG", width, height, 1, fmt)
    if clean.mode == "RGB":
        # Too big as lossless: store a JPEG instead (same pixels, lossy).
        return _finish(_encode_jpeg(clean), "JPEG", width, height, 1, fmt)
    raise _too_large("PNG", len(data))


def _encode_jpeg(clean: Image.Image) -> bytes:
    data = b""
    for q in _JPEG_QUALITIES:
        data = _encode(clean, "JPEG", quality=q, optimize=True)
        if len(data) <= MAX_OUTPUT_BYTES:
            return data
    raise _too_large("JPEG", len(data))


# ── Animated GIF ─────────────────────────────────────────────────────────────

def _process_animated_gif(im: Image.Image, scan: _GifScan) -> Processed:
    canvas = (scan.width, scan.height)
    target = _fit(*canvas)
    frames: list[Image.Image] = []
    durations: list[int] = []
    loop = 0
    try:
        loop = int(im.info.get("loop", 0) or 0)
        for index in range(MAX_GIF_FRAMES + 1):
            if index > 0:
                try:
                    im.seek(index)
                except EOFError:
                    break
            if index >= MAX_GIF_FRAMES or index >= scan.frames:
                # The scanner counted fewer frames than the decoder finds: the
                # file is not what it says it is.
                raise ImageRefused(TOO_MANY_FRAMES, "GIF frame count does not match its structure.")
            _check_size(*im.size)
            if im.size[0] > canvas[0] or im.size[1] > canvas[1]:
                raise ImageRefused(CORRUPT, "GIF frame overflows the canvas.")
            im.load()
            frame = im.convert("RGBA")             # Pillow composites disposal for us
            if frame.size != canvas:
                full = Image.new("RGBA", canvas, (0, 0, 0, 0))
                full.paste(frame, (0, 0))
                frame = full
            frame = _resize(frame, target)
            clean = Image.frombytes("RGBA", frame.size, frame.tobytes())
            frames.append(clean)
            duration = im.info.get("duration", 100)
            try:
                duration = int(duration)
            except (TypeError, ValueError):
                duration = 100
            durations.append(max(_GIF_MIN_DURATION_MS, min(_GIF_MAX_DURATION_MS, duration)))
    except ImageRefused:
        raise
    except Exception as e:
        raise ImageRefused(CORRUPT, "The animated GIF could not be decoded.") from e

    if len(frames) < 2:
        # Declared frames the decoder could not produce: store the one we have.
        return _finish(
            _encode(_to_clean(frames[0], "RGBA" if _any_alpha(frames[0]) else "RGB"),
                    "PNG", compress_level=_PNG_COMPRESS_LEVEL),
            "PNG", frames[0].size[0], frames[0].size[1], 1, "GIF",
        )

    palettised = [_quantize(f) for f in frames]
    try:
        data = _encode(
            palettised[0], "GIF", save_all=True, append_images=palettised[1:],
            duration=durations, loop=max(0, min(65535, loop)),
        )
    except Exception as e:
        raise ImageRefused(CORRUPT, "The animated GIF could not be re-encoded.") from e
    width, height = palettised[0].size
    return _finish(data, "GIF", width, height, len(palettised), "GIF")


def _any_alpha(frame: Image.Image) -> bool:
    extrema = frame.getextrema()
    return frame.mode == "RGBA" and extrema[3][0] < 255


def _quantize(frame: Image.Image) -> Image.Image:
    """RGBA frame → 256-colour palette frame (fast octree; it carries alpha).

    ``transparency`` on the result is the GIF transparent index, a structural
    field of the new file, not metadata from the upload.
    """
    if not _any_alpha(frame):
        frame = Image.frombytes("RGB", frame.size, frame.convert("RGB").tobytes())
    pal = frame.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    if frame.mode == "RGBA" and pal.palette is not None and pal.palette.mode == "RGBA":
        for rgba, index in pal.palette.colors.items():
            if rgba[3] == 0:
                pal.info["transparency"] = index
                break
    return pal


# ── Entry point ──────────────────────────────────────────────────────────────

def process(data: bytes) -> Processed:
    """Decode, strip, resize and re-encode an uploaded image.

    Raises :class:`ImageRefused` (a ``ValueError``) with a ``code`` from `CODES`
    for anything that is not stored. Never raises anything else for bad input.
    """
    if isinstance(data, (bytearray, memoryview)):
        data = bytes(data)
    if not isinstance(data, bytes):
        raise TypeError("process() takes bytes")
    if len(data) == 0:
        raise ImageRefused(EMPTY, "The file is empty.")
    if len(data) > MAX_INPUT_BYTES:
        raise ImageRefused(
            TOO_LARGE,
            f"The file is {len(data):,} bytes; the limit is {MAX_INPUT_BYTES:,} bytes (5 MiB).",
        )
    fmt = sniff(data)
    if fmt is None:
        raise ImageRefused(UNSUPPORTED, "Only JPEG, PNG, WebP and GIF images are accepted.")

    scan: Optional[_GifScan] = None
    if fmt == "GIF":
        scan = _scan_gif(data)                     # frames and canvas before decoding

    im = _open(data, fmt)
    try:
        if scan is not None and scan.frames > 1:
            return _process_animated_gif(im, scan)
        return _process_still(im, fmt)
    finally:
        try:
            im.close()
        except Exception:
            pass
