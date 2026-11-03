"""
Layer 1 S4-7: link cards, the pure parts (no database, no network).

Which link a post's card is for (the UI's linkify rules), how it is
normalised and keyed, and the bounded head parser: priorities between
og:/twitter:/<title>/description, plain text only, scripts and comments
ignored, huge or hostile input cut short and fast.

Run: cd platform && .venv/bin/python -m pytest tests/services/test_link_cards.py -v
"""
import hashlib
import time

import pytest

from src.services import link_cards as lc


# ── Which link ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, url", [
    ("see https://example.com/a?b=1 now", "https://example.com/a?b=1"),
    ("http://example.com", "http://example.com"),
    ("(https://example.com/x).", "https://example.com/x"),
    ("end https://example.com/page!?", "https://example.com/page"),
    ("two https://a.com and https://b.com", "https://a.com"),
    ('quote "https://example.com/q" done', "https://example.com/q"),
    ("<https://example.com/angle>", "https://example.com/angle"),
    ("tag https://example.com/#frag", "https://example.com/#frag"),
    ("first bad https:// then https://ok.com", "https://ok.com"),
])
def test_first_url(text, url):
    assert lc.first_url(text) == url


@pytest.mark.parametrize("text", [
    "", None, "no link", "www.example.com", "ftp://example.com", "HTTPS://EXAMPLE.COM",
    "https://", "https://.", "https:///path", "https://?q", "javascript:alert(1)",
])
def test_no_url(text):
    assert lc.first_url(text) is None


@pytest.mark.parametrize("raw, norm", [
    ("HTTPS://Example.COM", "https://example.com/"),
    ("https://example.com:443/a#b", "https://example.com/a"),
    ("http://example.com:80/?q=1", "http://example.com/?q=1"),
    ("https://bücher.de/x", "https://xn--bcher-kva.de/x"),
    ("https://example.com/A/B", "https://example.com/A/B"),
])
def test_normalise(raw, norm):
    assert lc.normalise(raw) == norm


def test_normalise_keeps_an_unfetchable_url_without_fragment():
    assert lc.normalise("https://localhost:8080/x#y") == "https://localhost:8080/x"
    assert lc.normalise("https://agentx.social/p") == "https://agentx.social/p"


def test_url_key_is_sha256_hex_and_no_link_marker():
    k = lc.url_key("https://example.com/")
    assert k == hashlib.sha256(b"https://example.com/").hexdigest() and len(k) == 64
    assert lc.NO_LINK_KEY == hashlib.sha256(b"").hexdigest()


# ── Parsing ──────────────────────────────────────────────────────────────────

BASE = "https://example.com/dir/page"


def _page(head: str, body: str = "<p>hi</p>") -> bytes:
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>".encode()


def test_og_tags_win():
    meta = lc.parse_card(_page(
        '<title>Plain title</title>'
        '<meta name="description" content="plain desc">'
        '<meta property="og:title" content="OG title">'
        '<meta name="twitter:title" content="TW title">'
        '<meta property="og:description" content="OG desc">'
        '<meta property="og:site_name" content="Example">'
        '<meta property="og:image" content="/img/card.png">'
    ), BASE)
    assert meta == lc.CardMeta("OG title", "OG desc", "Example", "https://example.com/img/card.png")


def test_twitter_then_title_and_description_fallbacks():
    meta = lc.parse_card(_page(
        '<title>Plain title</title><meta name="twitter:description" content="tw desc">'
        '<meta name="twitter:image" content="img.jpg">'
    ), BASE)
    assert meta.title == "Plain title" and meta.description == "tw desc"
    assert meta.image_url == "https://example.com/dir/img.jpg"
    assert lc.parse_card(_page('<meta name="description" content="d">'), BASE).description == "d"


def test_first_of_a_repeated_tag_and_case_insensitive_keys():
    meta = lc.parse_card(_page(
        '<META PROPERTY="OG:TITLE" CONTENT="one"><meta property="og:title" content="two">'
    ), BASE)
    assert meta.title == "one"


def test_entities_are_decoded_and_markup_stays_text():
    meta = lc.parse_card(_page(
        '<meta property="og:title" content="Tom &amp; Jerry &lt;b&gt;bold&lt;/b&gt; &#x1F600;">'
        '<title>x</title>'
    ), BASE)
    assert meta.title == "Tom & Jerry <b>bold</b> \U0001F600"


def test_script_style_and_comments_do_not_leak():
    meta = lc.parse_card(_page(
        '<script>var s = "<title>evil</title><meta property=og:title content=evil>";</script>'
        '<style>title{}</style><!-- <title>comment</title> -->'
        '<title>Real</title>'
    ), BASE)
    assert meta.title == "Real" and meta.description is None


def test_nothing_after_body_counts():
    meta = lc.parse_card(_page("", '<meta property="og:title" content="in body"><title>b</title>'), BASE)
    assert meta.empty and meta.title is None


def test_whitespace_controls_and_invisible_characters_are_removed():
    meta = lc.parse_card(_page(
        '<title>\n  Hello\t\x00 ‮world​  \r\n</title>'
    ), BASE)
    assert meta.title == "Hello world"


def test_lengths_are_capped():
    meta = lc.parse_card(_page(
        f'<meta property="og:title" content="{"t" * 5000}">'
        f'<meta property="og:description" content="{"d" * 5000}">'
        f'<meta property="og:site_name" content="{"s" * 5000}">'
    ), BASE)
    assert len(meta.title) == lc.MAX_TITLE and meta.title.endswith("…")
    assert len(meta.description) == lc.MAX_DESCRIPTION
    assert len(meta.site_name) == lc.MAX_SITE_NAME


def test_empty_page_and_garbage_never_raise():
    for data in (b"", b"\x00\xff\xfe" * 100, b"<<<>>>", b"<meta", b"<title>unclosed", "naïve".encode()):
        lc.parse_card(data, BASE)
    assert lc.parse_card(b"<title>unclosed", BASE).title == "unclosed"


@pytest.mark.parametrize("value, expected", [
    ("javascript:alert(1)", None),
    ("data:image/png;base64,AAAA", None),
    ("file:///etc/passwd", None),
    ("//cdn.example.org/i.png", "https://cdn.example.org/i.png"),
    ("http://other.example/i.png", "http://other.example/i.png"),
    ("  ", None),
    ("/a\nb.png", None),
    ("/" + "a" * 3000, None),
])
def test_image_url(value, expected):
    meta = lc.parse_card(_page(f'<title>t</title><meta property="og:image" content="{value}">'), BASE)
    assert meta.image_url == expected


def test_charset_from_meta_and_bom():
    latin = '<html><head><meta charset="iso-8859-1"><title>café</title></head></html>'.encode("latin-1")
    assert lc.parse_card(latin, BASE).title == "café"
    assert lc.parse_card(b"\xef\xbb\xbf<title>bom</title>", BASE).title == "bom"
    bogus = b'<meta charset="rot13"><title>abc</title>'
    assert lc.parse_card(bogus, BASE).title == "abc"
    seven = b'<meta charset="utf-7"><title>+ADw-script+AD4-</title>'
    assert lc.parse_card(seven, BASE).title == "+ADw-script+AD4-"


def test_tag_cap_stops_the_parser():
    head = "<meta>" * (lc.MAX_TAGS + 10) + '<meta property="og:title" content="late">'
    assert lc.parse_card(_page(head), BASE).title is None


@pytest.mark.parametrize("payload", [
    b"<" * 1_000_000,
    b"<!--" * 250_000,
    b"<a " * 330_000,
    b"&#" * 500_000,
    b'<meta content="' + b"x" * 1_000_000,
    b"<title>" + b"y" * 1_000_000,
    b"<![CDATA[" * 100_000,
])
def test_hostile_megabyte_is_fast(payload):
    started = time.monotonic()
    meta = lc.parse_card(payload, BASE)
    assert time.monotonic() - started < 3.0
    if payload.startswith(b"<title>"):
        assert len(meta.title) == lc.MAX_TITLE


def test_switch(monkeypatch):
    class S:
        link_cards_enabled = "false"
    for value, on in (("false", False), ("", False), ("on", False), ("1", True), ("TRUE", True), (" yes ", True)):
        S.link_cards_enabled = value
        assert lc.link_cards_enabled(S) is on


def test_scheduler_entry():
    from src.jobs.scheduler import JOBS, LINK_CARDS_INTERVAL_SECONDS
    entry = {job.name: job for job in JOBS}["link_cards"]
    assert LINK_CARDS_INTERVAL_SECONDS == 60.0 == entry.interval
    assert entry.run is lc.run_link_cards and entry.enabled is lc.link_cards_enabled
