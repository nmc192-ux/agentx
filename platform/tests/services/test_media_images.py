"""Layer 1 S4-2: the image pipeline (pure, no DB).

Every test builds its own file in memory with Pillow or by hand (crafted
headers), feeds the bytes to ``media_images.process`` and inspects the output
bytes with small independent parsers (JPEG segments, PNG chunks, WebP chunks,
GIF blocks), so "the metadata is gone" is checked on the file, not on what
Pillow reports.
"""
from __future__ import annotations

import hashlib
import io
import re
import struct
import time
import zlib

import pytest
from PIL import ExifTags, Image, ImageOps, TiffImagePlugin

from src.services import media_images as M
from src.services.media_images import ImageRefused, Processed, process, sniff

SECRET_COMMENT = b"secret-comment-7a9f"
SECRET_XMP = b"<x:xmpmeta xmlns:x='adobe:ns:meta/'>secret-xmp-7a9f</x:xmpmeta>"
SECRET_ICC = b"ICC-PROFILE-BODY-7a9f" * 8
SECRET_TEXT = "secret-text-7a9f"
HTML_PAYLOAD = b"<html><script>alert('xss-7a9f')</script></html>"


# ── Builders ─────────────────────────────────────────────────────────────────

def gps_exif(orientation: int | None = None) -> bytes:
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    exif[0x010E] = SECRET_TEXT                                     # ImageDescription
    exif[0x0110] = "SecretCam 7a9f"                                # Model
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    r = TiffImagePlugin.IFDRational
    gps[1] = "N"
    gps[2] = (r(51, 1), r(30, 1), r(1234, 100))                    # GPSLatitude
    gps[3] = "W"
    gps[4] = (r(0, 1), r(7, 1), r(4321, 100))                      # GPSLongitude
    return exif.tobytes()


def make_jpeg(size=(120, 80), mode="RGB", quality=90, **save) -> bytes:
    im = Image.new(mode, size, (200, 40, 40) if mode == "RGB" else 128)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, **save)
    return buf.getvalue()


def jpeg_with_everything(orientation=None, size=(120, 80)) -> bytes:
    return make_jpeg(
        size, exif=gps_exif(orientation), icc_profile=SECRET_ICC,
        comment=SECRET_COMMENT, xmp=SECRET_XMP,
    )


def make_png(size=(64, 48), mode="RGBA", **save) -> bytes:
    colour = {"RGBA": (10, 200, 30, 120), "RGB": (10, 200, 30), "L": 77, "LA": (77, 90)}.get(mode, 0)
    im = Image.new(mode, size, colour)
    buf = io.BytesIO()
    im.save(buf, "PNG", **save)
    return buf.getvalue()


def png_with_everything() -> bytes:
    from PIL.PngImagePlugin import PngInfo
    info = PngInfo()
    info.add_text("Author", SECRET_TEXT)
    info.add_itxt("Comment", SECRET_TEXT, lang="en", tkey="Comment")
    info.add_text("Big", SECRET_TEXT * 50, zip=True)
    return make_png(pnginfo=info, exif=gps_exif(), icc_profile=SECRET_ICC)


def make_webp(size=(64, 48), mode="RGB", **save) -> bytes:
    im = Image.new(mode, size, (20, 30, 240, 100) if mode == "RGBA" else (20, 30, 240))
    buf = io.BytesIO()
    im.save(buf, "WEBP", **save)
    return buf.getvalue()


def make_gif(size=(40, 30), frames=1, duration=80, loop=0, comment=None, transparent=False) -> bytes:
    images = []
    for i in range(frames):
        if transparent:
            f = Image.new("RGBA", size, (0, 0, 0, 0))
            f.paste((255, (i * 37) % 256, 0, 255), (i % size[0], 0, min(size[0], i % size[0] + 8), size[1]))
        else:
            f = Image.new("RGB", size, (255, (i * 37) % 256, (i * 91) % 256))
            f.paste((0, 0, 0), (i % size[0], 0, min(size[0], i % size[0] + 3), size[1]))
        images.append(f)
    buf = io.BytesIO()
    kw = {"save_all": True, "append_images": images[1:], "duration": duration, "loop": loop} if frames > 1 else {}
    if comment is not None:
        kw["comment"] = comment
    images[0].save(buf, "GIF", **kw)
    return buf.getvalue()


def craft_png_header(width: int, height: int) -> bytes:
    """A syntactically valid PNG whose IHDR claims ``width × height``."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00" * 16)) + chunk(b"IEND", b""))


def craft_jpeg_header(width: int, height: int) -> bytes:
    """SOI + APP0 + SOF0 claiming ``width × height`` + the start of a scan."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    sos = b"\xff\xda" + struct.pack(">HB", 12, 3) + b"\x01\x00\x02\x11\x03\x11\x00\x3f\x00" + b"\x00" * 64 + b"\xff\xd9"
    return b"\xff\xd8" + app0 + sof0 + sos


def craft_gif(logical=(1, 1), frames=((0, 0, 1, 1),), trailer=True, junk_block: bytes = b"",
              comment: bytes | None = None) -> bytes:
    """A GIF from raw blocks: logical screen, a 2-colour global table, frames
    with a tiny (invalid) LZW payload. Enough for the structure scan; the
    decoder may or may not like the pixel data."""
    out = b"GIF89a" + struct.pack("<HHBBB", logical[0], logical[1], 0x80, 0, 0) + b"\x00\x00\x00\xff\xff\xff"
    if comment is not None:
        out += b"\x21\xfe" + bytes([min(255, len(comment))]) + comment[:255] + b"\x00"
    out += junk_block
    for (x, y, w, h) in frames:
        out += b"\x2c" + struct.pack("<HHHHB", x, y, w, h, 0) + b"\x02" + b"\x02\x44\x01" + b"\x00"
    if trailer:
        out += b"\x3b"
    return out


# ── Independent parsers of the output files ─────────────────────────────────

def jpeg_segments(data: bytes) -> list[int]:
    """Marker codes of every segment before the scan (APPn, COM, DQT, SOF, ...)."""
    assert data[:2] == b"\xff\xd8"
    markers, pos = [], 2
    while pos + 4 <= len(data):
        assert data[pos] == 0xFF, "segment boundary lost"
        marker = data[pos + 1]
        if marker == 0xD9:
            break
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        markers.append(marker)
        pos += 2 + length
        if marker == 0xDA:                        # start of scan: entropy data follows
            break
    return markers


def png_chunks(data: bytes) -> list[bytes]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    kinds, pos = [], 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        kinds.append(kind)
        pos += 12 + length
    return kinds


def webp_chunks(data: bytes) -> list[bytes]:
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    kinds, pos = [], 12
    while pos + 8 <= len(data):
        kind = data[pos:pos + 4]
        length = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        kinds.append(kind)
        pos += 8 + length + (length & 1)
    return kinds


def gif_blocks(data: bytes) -> dict:
    """Counts of image descriptors and extension labels; refuses junk."""
    assert data[:6] in (b"GIF87a", b"GIF89a")
    flags = data[10]
    pos = 13 + (3 * (2 << (flags & 7)) if flags & 0x80 else 0)
    out = {"frames": 0, "extensions": []}

    def skip(p):
        while True:
            n = data[p]
            p += 1
            if n == 0:
                return p
            p += n

    while pos < len(data):
        b = data[pos]
        pos += 1
        if b == 0x3B:
            break
        if b == 0x21:
            out["extensions"].append(data[pos])
            pos = skip(pos + 1)
        elif b == 0x2C:
            out["frames"] += 1
            iflags = data[pos + 8]
            pos += 9
            if iflags & 0x80:
                pos += 3 * (2 << (iflags & 7))
            pos = skip(pos + 1)
        else:
            raise AssertionError(f"junk block {b:#x}")
    return out


def assert_clean(p: Processed) -> None:
    """The stored file carries no metadata of any kind and nothing after the image."""
    data = p.data
    for needle in (SECRET_COMMENT, SECRET_XMP, SECRET_ICC[:20], SECRET_TEXT.encode(),
                   b"SecretCam", HTML_PAYLOAD, b"<script", b"Exif\x00\x00", b"ICC_PROFILE",
                   b"ns.adobe.com", b"GPS"):
        assert needle not in data, needle
    if p.mime == "image/jpeg":
        segs = jpeg_segments(data)
        # Only JFIF APP0, quantisation, frame, Huffman, (restart), scan.
        assert all(s in (0xE0, 0xDB, 0xC0, 0xC2, 0xC4, 0xDD, 0xDA) for s in segs), [hex(s) for s in segs]
        assert 0xE1 not in segs and 0xE2 not in segs and 0xFE not in segs
    elif p.mime == "image/png":
        kinds = png_chunks(data)
        assert set(kinds) <= {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"}, kinds
        assert kinds[-1] == b"IEND" and data.endswith(struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF))
    elif p.mime == "image/webp":
        kinds = webp_chunks(data)
        assert set(kinds) <= {b"VP8 ", b"VP8L", b"VP8X", b"ALPH"}, kinds
    elif p.mime == "image/gif":
        blocks = gif_blocks(data)
        assert blocks["frames"] == p.frames
        # Graphic control (0xF9) and the NETSCAPE loop application block (0xFF)
        # are structure; a comment (0xFE) or plain text (0x01) is metadata.
        assert set(blocks["extensions"]) <= {0xF9, 0xFF}, blocks["extensions"]
        assert data.endswith(b"\x3b")
    # The declared type is what the bytes are, and the row the API will write fits migration 056.
    assert sniff(data) == {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP", "image/gif": "GIF"}[p.mime]
    assert (p.mime, p.ext) in M.MIME_BY_FORMAT.values()
    assert p.sha256 == hashlib.sha256(data).hexdigest()
    assert 1 <= p.width <= M.MAX_SIDE and 1 <= p.height <= M.MAX_SIDE
    assert 1 <= p.size <= M.MAX_OUTPUT_BYTES
    back = Image.open(io.BytesIO(data))
    assert back.size == (p.width, p.height)
    assert not back.getexif()
    assert "icc_profile" not in back.info and "comment" not in back.info and "xmp" not in back.info


def refused(data: bytes, code: str) -> ImageRefused:
    with pytest.raises(ImageRefused) as ei:
        process(data)
    assert ei.value.code == code, (ei.value.code, str(ei.value))
    assert str(ei.value)
    return ei.value


# ── Metadata stripping ──────────────────────────────────────────────────────

def test_jpeg_exif_gps_icc_comment_xmp_removed():
    src = jpeg_with_everything()
    # The fixture really carries all of it.
    assert SECRET_COMMENT in src and SECRET_XMP in src and b"ICC_PROFILE" in src
    gps = Image.open(io.BytesIO(src)).getexif().get_ifd(0x8825)
    assert gps[2][0] == 51
    p = process(src)
    assert p.mime == "image/jpeg" and p.ext == "jpg" and p.frames == 1 and p.source_format == "JPEG"
    assert_clean(p)
    assert dict(Image.open(io.BytesIO(p.data)).getexif().get_ifd(0x8825)) == {}


def test_jpeg_exif_orientation_applied_then_dropped():
    src = jpeg_with_everything(orientation=6, size=(120, 80))
    p = process(src)
    assert (p.width, p.height) == (80, 120)
    assert_clean(p)
    assert Image.open(io.BytesIO(p.data)).getexif().get(0x0112) is None
    # Pixels match what a viewer that honours the tag would show.
    want = ImageOps.exif_transpose(Image.open(io.BytesIO(src))).convert("RGB")
    got = Image.open(io.BytesIO(p.data)).convert("RGB")
    assert got.size == want.size


def test_jpeg_broken_exif_is_dropped_not_fatal():
    src = make_jpeg(exif=b"Exif\x00\x00" + b"\xff" * 40)
    p = process(src)
    assert_clean(p)


def test_png_text_exif_icc_removed_alpha_kept():
    src = png_with_everything()
    assert b"tEXt" in src and b"iTXt" in src and b"zTXt" in src and b"eXIf" in src and b"iCCP" in src
    p = process(src)
    assert p.mime == "image/png" and p.ext == "png"
    assert_clean(p)
    back = Image.open(io.BytesIO(p.data))
    assert back.mode == "RGBA" and back.getpixel((0, 0)) == (10, 200, 30, 120)
    assert back.text == {}


def test_webp_exif_icc_xmp_removed_alpha_kept():
    src = make_webp(mode="RGBA", lossless=True, exif=gps_exif(), icc_profile=SECRET_ICC, xmp=SECRET_XMP)
    assert b"EXIF" in src and b"ICCP" in src and b"XMP " in src
    p = process(src)
    assert p.mime == "image/webp" and p.ext == "webp"
    assert_clean(p)
    assert Image.open(io.BytesIO(p.data)).mode == "RGBA"


def test_gif_comment_removed_still_becomes_png():
    src = make_gif(frames=1, comment=SECRET_COMMENT)
    assert SECRET_COMMENT in src
    p = process(src)
    assert p.mime == "image/png" and p.frames == 1 and p.source_format == "GIF"
    assert_clean(p)


def test_animated_gif_keeps_frames_timing_and_loop_drops_comment():
    src = make_gif(size=(40, 30), frames=6, duration=[50, 60, 70, 80, 90, 100], loop=3, comment=SECRET_COMMENT)
    p = process(src)
    assert p.mime == "image/gif" and p.ext == "gif" and p.frames == 6 and p.animated
    assert (p.width, p.height) == (40, 30)
    assert_clean(p)
    back = Image.open(io.BytesIO(p.data))
    assert back.n_frames == 6 and back.info["loop"] == 3
    durations = []
    for i in range(6):
        back.seek(i)
        durations.append(back.info["duration"])
    assert durations == [50, 60, 70, 80, 90, 100]
    # Frame content survives: each frame has its black bar where the source had it.
    back.seek(4)
    assert back.convert("RGB").getpixel((5, 10)) == (0, 0, 0)


def test_animated_gif_with_transparency_keeps_it():
    src = make_gif(size=(32, 16), frames=4, transparent=True)
    p = process(src)
    assert p.frames == 4
    assert_clean(p)
    back = Image.open(io.BytesIO(p.data))
    back.seek(2)
    rgba = back.convert("RGBA")
    assert rgba.getpixel((31, 8))[3] == 0            # never painted: transparent
    assert rgba.getpixel((3, 8))[3] == 255           # painted by the first frame


# ── Polyglots and hidden payloads ───────────────────────────────────────────

def test_gif_html_polyglot_still_is_rewritten_without_the_html():
    src = make_gif(frames=1, comment=HTML_PAYLOAD) + HTML_PAYLOAD      # comment + trailing bytes
    assert src.count(b"<script") == 2
    p = process(src)
    assert p.mime == "image/png"
    assert_clean(p)


def test_gif_html_polyglot_animated_is_rewritten_without_the_html():
    src = make_gif(frames=3, comment=HTML_PAYLOAD) + HTML_PAYLOAD
    p = process(src)
    assert p.mime == "image/gif" and p.frames == 3
    assert_clean(p)


def test_jpeg_with_html_in_comment_and_after_eoi():
    src = make_jpeg(comment=HTML_PAYLOAD) + HTML_PAYLOAD
    p = process(src)
    assert_clean(p)
    assert p.data.endswith(b"\xff\xd9")


def test_png_with_html_in_text_chunk_and_after_iend():
    from PIL.PngImagePlugin import PngInfo
    info = PngInfo()
    info.add_text("payload", HTML_PAYLOAD.decode())
    src = make_png(pnginfo=info) + HTML_PAYLOAD
    p = process(src)
    assert_clean(p)


def test_webp_with_trailing_html():
    src = make_webp() + HTML_PAYLOAD
    p = process(src)
    assert_clean(p)


# ── Sniffing: content decides, never the name or Content-Type ───────────────

def test_sniff_by_magic_bytes():
    assert sniff(make_jpeg()) == "JPEG"
    assert sniff(make_png()) == "PNG"
    assert sniff(make_webp()) == "WEBP"
    assert sniff(make_gif()) == "GIF"
    assert sniff(b"") is None
    assert sniff(b"RIFF\x00\x00\x00\x00WAVE") is None
    assert sniff(b"\xff\xd8\x00") is None


def test_wrong_extension_is_irrelevant_the_bytes_decide():
    png_bytes_called_jpg = make_png()
    p = process(png_bytes_called_jpg)
    assert p.mime == "image/png" and p.ext == "png"


@pytest.mark.parametrize("name, data", [
    ("empty-ish", b"\x00"),
    ("text", b"hello world"),
    ("html", HTML_PAYLOAD),
    ("svg", b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>"),
    ("pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\n%%EOF"),
    ("heic", b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"),
    ("avif", b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1"),
    ("riff-not-webp", b"RIFF\x10\x00\x00\x00WAVEfmt " + b"\x00" * 16),
    ("jpeg-sig-too-short", b"\xff\xd8"),
])
def test_unsupported_types_refused_by_content(name, data):
    refused(data, M.UNSUPPORTED)


@pytest.mark.parametrize("fmt", ["BMP", "TIFF", "PPM", "ICO", "TGA"])
def test_real_other_formats_refused(fmt):
    im = Image.new("RGB", (16, 16), (1, 2, 3))
    buf = io.BytesIO()
    im.save(buf, fmt)
    refused(buf.getvalue(), M.UNSUPPORTED)


def test_png_body_behind_gif_signature_is_corrupt_not_decoded_as_png():
    body = make_png()
    refused(b"GIF89a" + body[6:], M.CORRUPT)


def test_gif_body_behind_png_signature_is_corrupt():
    body = make_gif()
    refused(b"\x89PNG\r\n\x1a\n" + body[8:], M.CORRUPT)


def test_jpeg_body_behind_webp_signature_is_corrupt():
    body = make_jpeg()
    refused(b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body, M.CORRUPT)


# ── Size limits ──────────────────────────────────────────────────────────────

def test_empty_refused():
    refused(b"", M.EMPTY)


def test_over_5mib_refused_before_decoding():
    data = make_jpeg() + b"\x00" * (M.MAX_INPUT_BYTES + 1 - len(make_jpeg()))
    assert len(data) == M.MAX_INPUT_BYTES + 1
    t0 = time.monotonic()
    e = refused(data, M.TOO_LARGE)
    assert time.monotonic() - t0 < 0.5
    assert "5 MiB" in str(e)


def test_exactly_5mib_is_not_refused_for_size():
    body = make_jpeg()
    data = body + b"\x00" * (M.MAX_INPUT_BYTES - len(body))     # padding after EOI is ignored
    p = process(data)
    assert_clean(p)


def test_bytearray_and_memoryview_accepted_other_types_not():
    p = process(bytearray(make_png()))
    assert p.mime == "image/png"
    p = process(memoryview(make_png()))
    assert p.mime == "image/png"
    with pytest.raises(TypeError):
        process("not bytes")  # type: ignore[arg-type]


# ── Decompression bombs: refused from the header, fast ──────────────────────

@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
@pytest.mark.parametrize("side", [30_000, 10_000, 6_400])
def test_png_header_bomb_refused_fast(side):
    data = craft_png_header(side, side)
    assert len(data) < 200
    t0 = time.monotonic()
    refused(data, M.TOO_MANY_PIXELS)
    assert time.monotonic() - t0 < 0.5


def test_png_just_under_pixel_cap_is_opened_not_refused_for_pixels():
    # 6324² = 39.99 MP: under the cap, so the only complaint is the fake IDAT.
    e = refused(craft_png_header(6324, 6324), M.CORRUPT)
    assert e.code == M.CORRUPT


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
@pytest.mark.parametrize("w, h", [(65_535, 65_535), (20_000, 20_000), (8_000, 6_000)])
def test_jpeg_header_bomb_refused_fast(w, h):
    data = craft_jpeg_header(w, h)
    t0 = time.monotonic()
    refused(data, M.TOO_MANY_PIXELS)
    assert time.monotonic() - t0 < 0.5


def test_jpeg_zero_dimension_refused():
    refused(craft_jpeg_header(0, 100), M.CORRUPT)


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_gif_logical_screen_bomb_refused_before_pillow():
    refused(craft_gif(logical=(65_535, 65_535), frames=((0, 0, 1, 1),)), M.TOO_MANY_PIXELS)


def test_gif_frame_descriptor_bigger_than_logical_screen_is_the_real_size():
    # Pillow grows the canvas to the frame; the scanner must see it coming.
    refused(craft_gif(logical=(1, 1), frames=((0, 0, 20_000, 20_000),)), M.TOO_MANY_PIXELS)
    refused(craft_gif(logical=(1, 1), frames=((60_000, 60_000, 10, 10),)), M.TOO_MANY_PIXELS)
    refused(craft_gif(logical=(1, 1), frames=((0, 0, 1, 1), (0, 0, 10_000, 10_000))), M.TOO_MANY_PIXELS)


def test_gif_too_many_frames_refused_before_decoding():
    many = craft_gif(logical=(2, 2), frames=((0, 0, 1, 1),) * (M.MAX_GIF_FRAMES + 1))
    t0 = time.monotonic()
    refused(many, M.TOO_MANY_FRAMES)
    assert time.monotonic() - t0 < 0.5


def test_gif_exactly_max_frames_is_allowed():
    src = make_gif(size=(8, 8), frames=M.MAX_GIF_FRAMES)
    assert Image.open(io.BytesIO(src)).n_frames == M.MAX_GIF_FRAMES
    p = process(src)
    assert p.frames == M.MAX_GIF_FRAMES
    assert_clean(p)


def test_gif_total_pixel_budget_refused_before_decoding():
    # 20 frames × 2000 × 2000 = 80 MP > the animation budget; each frame alone is fine.
    data = craft_gif(logical=(2000, 2000), frames=((0, 0, 2000, 2000),) * 20)
    refused(data, M.TOO_MANY_PIXELS)
    # One frame of 2000 × 2000 is under every cap: only the fake pixel data fails.
    refused(craft_gif(logical=(2000, 2000), frames=((0, 0, 2000, 2000),)), M.CORRUPT)


def test_gif_frame_with_zero_dimension_refused():
    refused(craft_gif(frames=((0, 0, 0, 10),)), M.CORRUPT)


def test_gif_without_any_frame_refused():
    refused(craft_gif(frames=()), M.CORRUPT)


def test_gif_junk_block_refused_not_stepped_over():
    # Pillow would skip the 0x7f byte and still find the frame; we refuse.
    refused(craft_gif(junk_block=b"\x7f"), M.CORRUPT)


def test_gif_truncated_inside_a_block_refused():
    src = make_gif(frames=3)
    refused(src[:-10], M.CORRUPT)
    refused(src[:20], M.CORRUPT)


def test_gif_missing_trailer_is_tolerated_like_pillow():
    src = make_gif(frames=1)
    assert src.endswith(b"\x3b")
    p = process(src[:-1])
    assert p.mime == "image/png"


def test_gif_scan_counts_frames_exactly():
    scan = M._scan_gif(make_gif(size=(12, 7), frames=5))
    assert scan.frames == 5 and (scan.width, scan.height) == (12, 7)
    scan = M._scan_gif(craft_gif(logical=(5, 5), frames=((0, 0, 3, 3), (4, 4, 6, 6))))
    assert scan.frames == 2 and (scan.width, scan.height) == (10, 10)


# ── Corrupt and truncated files ─────────────────────────────────────────────

def test_truncated_jpeg_refused():
    src = make_jpeg(size=(400, 300))
    refused(src[: len(src) // 2], M.CORRUPT)      # header cut
    refused(src[: int(len(src) * 0.9)], M.CORRUPT)  # scan cut: open works, load fails


def test_truncated_png_refused():
    src = make_png(size=(200, 200))
    refused(src[: len(src) - 40], M.CORRUPT)
    refused(src[:30], M.CORRUPT)


def test_corrupt_png_idat_refused():
    src = bytearray(make_png(size=(64, 64)))
    i = src.find(b"IDAT")
    for k in range(i + 8, i + 40):
        src[k] ^= 0xFF
    refused(bytes(src), M.CORRUPT)


def test_truncated_webp_refused():
    src = make_webp(size=(200, 200))
    refused(src[: len(src) // 2], M.CORRUPT)


def test_garbage_after_signature_refused():
    refused(b"\x89PNG\r\n\x1a\n" + b"garbage" * 20, M.CORRUPT)
    refused(b"\xff\xd8\xff" + b"garbage" * 20, M.CORRUPT)
    refused(b"RIFF\x00\x01\x00\x00WEBP" + b"garbage" * 20, M.CORRUPT)
    refused(b"GIF89a" + b"garbage" * 20, M.CORRUPT)


# ── Resizing ─────────────────────────────────────────────────────────────────

def test_fit():
    assert M._fit(100, 50) == (100, 50)
    assert M._fit(2048, 2048) == (2048, 2048)
    assert M._fit(4096, 2048) == (2048, 1024)
    assert M._fit(5000, 1000) == (2048, 410)
    assert M._fit(1000, 5000) == (410, 2048)
    assert M._fit(3000, 3000) == (2048, 2048)
    assert M._fit(100_000, 1) == (2048, 1)
    assert M._fit(2049, 2049) == (2048, 2048)


def test_large_jpeg_resized_to_2048_longest_side():
    im = Image.effect_noise((5000, 1000), 60).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=40)
    assert len(buf.getvalue()) <= M.MAX_INPUT_BYTES
    p = process(buf.getvalue())
    assert (p.width, p.height) == (2048, 410)
    assert_clean(p)


def test_large_png_resized_keeps_alpha():
    src = make_png(size=(3000, 1500), mode="RGBA")
    p = process(src)
    assert (p.width, p.height) == (2048, 1024) and p.mime == "image/png"
    assert Image.open(io.BytesIO(p.data)).mode == "RGBA"


def test_large_animated_gif_frames_are_resized():
    src = make_gif(size=(2500, 100), frames=3)
    p = process(src)
    assert (p.width, p.height) == (2048, 82) and p.frames == 3
    back = Image.open(io.BytesIO(p.data))
    for i in range(3):
        back.seek(i)
        assert back.size == (2048, 82)


def test_small_image_is_not_upscaled():
    p = process(make_png(size=(3, 2)))
    assert (p.width, p.height) == (3, 2)


def test_one_pixel_image_ok():
    p = process(make_png(size=(1, 1)))
    assert (p.width, p.height) == (1, 1)


def test_oriented_large_jpeg_longest_side_still_2048():
    im = Image.new("RGB", (4000, 2000), (1, 2, 3))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=50, exif=gps_exif(orientation=6))
    p = process(buf.getvalue())
    assert (p.width, p.height) == (1024, 2048)
    assert_clean(p)


# ── Modes and formats ────────────────────────────────────────────────────────

def test_cmyk_jpeg_becomes_rgb_jpeg():
    im = Image.new("CMYK", (50, 40), (0, 255, 255, 0))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    p = process(buf.getvalue())
    assert p.mime == "image/jpeg" and Image.open(io.BytesIO(p.data)).mode == "RGB"
    assert_clean(p)


def test_grayscale_jpeg_ok():
    p = process(make_jpeg(mode="L"))
    assert p.mime == "image/jpeg"
    assert_clean(p)


def test_16bit_png_scaled_to_8bit_not_clipped():
    im = Image.new("I;16", (4, 4), 60000)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    p = process(buf.getvalue())
    back = Image.open(io.BytesIO(p.data))
    assert back.mode == "RGB" and back.getpixel((0, 0)) == (234, 234, 234)


def test_palette_png_with_transparency_becomes_rgba():
    im = Image.new("P", (8, 8), 0)
    im.putpalette([255, 0, 0, 0, 255, 0] + [0] * (256 * 3 - 6))
    buf = io.BytesIO()
    im.save(buf, "PNG", transparency=0)
    p = process(buf.getvalue())
    back = Image.open(io.BytesIO(p.data))
    assert back.mode == "RGBA" and back.getpixel((0, 0))[3] == 0


def test_opaque_png_stays_rgb_and_la_becomes_rgba():
    assert Image.open(io.BytesIO(process(make_png(mode="RGB")).data)).mode == "RGB"
    assert Image.open(io.BytesIO(process(make_png(mode="L")).data)).mode == "RGB"
    assert Image.open(io.BytesIO(process(make_png(mode="LA")).data)).mode == "RGBA"


def test_animated_webp_keeps_first_frame_only():
    frames = [Image.new("RGB", (16, 16), (i * 60, 0, 0)) for i in range(4)]
    buf = io.BytesIO()
    frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:], duration=100)
    assert Image.open(io.BytesIO(buf.getvalue())).n_frames == 4
    p = process(buf.getvalue())
    assert p.mime == "image/webp" and p.frames == 1 and not p.animated
    back = Image.open(io.BytesIO(p.data))
    assert getattr(back, "n_frames", 1) == 1
    assert back.convert("RGB").getpixel((0, 0))[0] < 30


def test_apng_keeps_first_frame_only():
    frames = [Image.new("RGB", (16, 16), (i * 60, 0, 0)) for i in range(3)]
    buf = io.BytesIO()
    frames[0].save(buf, "PNG", save_all=True, append_images=frames[1:], duration=100)
    assert Image.open(io.BytesIO(buf.getvalue())).n_frames == 3
    p = process(buf.getvalue())
    assert p.mime == "image/png" and p.frames == 1
    assert b"acTL" not in p.data and b"fcTL" not in p.data and b"fdAT" not in p.data


def test_lossless_webp_is_stored_as_webp():
    p = process(make_webp(lossless=True))
    assert p.mime == "image/webp"
    assert_clean(p)


# ── Output size cap ──────────────────────────────────────────────────────────

def test_output_cap_jpeg_lowers_quality_then_refuses(monkeypatch):
    im = Image.effect_noise((600, 600), 80).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    src = buf.getvalue()
    full = process(src)
    monkeypatch.setattr(M, "MAX_OUTPUT_BYTES", int(full.size * 0.9))
    lower = process(src)                             # a lower quality fits
    assert lower.size < full.size and lower.mime == "image/jpeg"
    monkeypatch.setattr(M, "MAX_OUTPUT_BYTES", 1000)
    e = refused(src, M.OUTPUT_TOO_LARGE)
    assert "JPEG" in str(e)


def test_output_cap_opaque_png_falls_back_to_jpeg(monkeypatch):
    im = Image.effect_noise((300, 300), 80).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    src = buf.getvalue()
    assert process(src).mime == "image/png"
    monkeypatch.setattr(M, "MAX_OUTPUT_BYTES", 60_000)
    p = process(src)
    assert p.mime == "image/jpeg" and p.ext == "jpg" and p.source_format == "PNG"
    assert_clean(p)


def test_output_cap_transparent_png_refused_not_flattened(monkeypatch):
    noise = Image.effect_noise((300, 300), 80).convert("L")
    im = Image.merge("RGBA", (noise, noise, noise, noise))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    monkeypatch.setattr(M, "MAX_OUTPUT_BYTES", 20_000)
    refused(buf.getvalue(), M.OUTPUT_TOO_LARGE)


def test_output_cap_webp_and_gif(monkeypatch):
    noise = Image.effect_noise((300, 300), 80).convert("RGB")
    buf = io.BytesIO()
    noise.save(buf, "WEBP", quality=95)
    monkeypatch.setattr(M, "MAX_OUTPUT_BYTES", 500)
    refused(buf.getvalue(), M.OUTPUT_TOO_LARGE)
    refused(make_gif(size=(100, 100), frames=4), M.OUTPUT_TOO_LARGE)


# ── Contract with the rest of S4 ─────────────────────────────────────────────

def test_processed_is_deterministic_and_complete():
    src = make_png(size=(20, 10))
    a, b = process(src), process(src)
    assert a == b
    assert a.sha256 == hashlib.sha256(a.data).hexdigest() and len(a.sha256) == 64
    assert a.size == len(a.data)
    assert a.source_format == "PNG"


def test_refusal_codes_are_stable_and_are_value_errors():
    assert M.CODES == {
        "empty", "too_large", "unsupported_type", "too_many_pixels",
        "too_many_frames", "corrupt", "output_too_large",
    }
    e = refused(b"", M.EMPTY)
    assert isinstance(e, ValueError) and e.message == str(e)
    with pytest.raises(AssertionError):
        ImageRefused("not-a-code", "x")


def test_types_match_migration_056_check_constraints():
    import pathlib
    migration = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions" / "056_media.py"
    text = migration.read_text()
    mimes = set(re.search(r"mime IN \(([^)]*)\)", text).group(1).replace("'", "").replace(" ", "").split(","))
    exts = set(re.search(r"ext IN \(([^)]*)\)", text).group(1).replace("'", "").replace(" ", "").split(","))
    assert mimes == {m for m, _ in M.MIME_BY_FORMAT.values()} == M.ALLOWED_MIMES
    assert exts == {e for _, e in M.MIME_BY_FORMAT.values()}
    assert "5242880" in text and M.MAX_OUTPUT_BYTES == 5242880
    assert "BETWEEN 1 AND 2048" in text and M.MAX_SIDE == 2048


def test_limits_are_what_the_layer_plan_says():
    assert M.MAX_INPUT_BYTES == 5 * 1024 * 1024
    assert M.MAX_SIDE == 2048
    assert M.MAX_PIXELS == 40_000_000
    assert M.MAX_GIF_FRAMES == 100


def test_pillow_is_pinned_in_requirements():
    import pathlib
    req = (pathlib.Path(__file__).resolve().parents[2] / "requirements.txt").read_text()
    m = re.search(r"^pillow==(\d+\.\d+\.\d+)$", req, re.M | re.I)
    assert m, "pillow must be pinned in platform/requirements.txt"
    import PIL
    assert PIL.__version__ == m.group(1)
