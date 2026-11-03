"""
Link cards — Layer 1 S4-7.

A post whose text carries an http(s) link gets a card under it: title,
description, site name and (optionally) a small image, read from the page's
``og:`` / ``twitter:`` tags, ``<title>`` and ``<meta name="description">``.

Where the work happens:

* **Never in a request.** The ``link_cards`` scheduler job (every minute,
  off unless ``LINK_CARDS_ENABLED`` is exactly 1/true/yes) picks up new
  public posts and fetches their first link through ``safe_fetch`` (the
  SSRF guard, S4-6). A failed fetch means no card, never an error to anyone.
* **Once per URL per 24 h.** Cards are cached in ``link_cards`` by
  ``url_key`` (sha256 of the normalised URL); a failure is cached too, so a
  dead or hostile link is not fetched again for a day.
* **Bounded.** At most `FETCHES_PER_RUN` page fetches per run (so per
  minute, across both API copies: the scheduler runs once), `CONCURRENCY`
  at a time, the whole run inside `RUN_BUDGET_SECONDS`. The HTML parser
  stops at ``<body>`` or after `MAX_TAGS` tags, keeps at most
  `MAX_ATTR_CHARS` of any attribute and returns plain text only.
* **Never the outside URL for an image.** The card image is fetched through
  the guard, rebuilt by the image pipeline (S4-2) and stored as a
  ``LINK_THUMB`` media row owned by the post's author. It is ``PENDING``
  when that author's own uploads would be (account under 7 days old) and is
  shown only once ``APPROVED``.
* **Not for held, hidden or non-public posts.** The job skips them (the
  server must not visit a link only a collective may see), and
  :func:`annotate` leaves the card off a hidden post.

Which link: the first one the UI would link (``ui/lib/linkify.ts``): it
starts with ``http://`` or ``https://``, runs to whitespace, ``<``, ``>`` or
``"``, and loses trailing ``.,;:!?)]}'``. A post the job looked at that has
no usable link points at the `NO_LINK_KEY` marker row, so it is not looked at
again.
"""
from __future__ import annotations

import asyncio
import codecs
import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable, Iterable, Optional
from urllib.parse import urljoin, urlsplit
from uuid import UUID, uuid4

from ..config import get_settings
from ..database import transaction
from . import media_images, media_store, safe_fetch

logger = logging.getLogger("agentx.link_cards")

__all__ = [
    "first_url", "normalise", "url_key", "parse_card", "CardMeta",
    "link_cards_enabled", "run_link_cards", "annotate", "NO_LINK_KEY",
]

_TRUE = frozenset({"1", "true", "yes"})

CACHE_HOURS = 24
LOOKBACK_HOURS = 24          # posts older than this never get a card
CANDIDATES_PER_RUN = 200     # posts looked at per run
FETCHES_PER_RUN = 20         # page fetches per run (the run is every minute)
CONCURRENCY = 4
RUN_BUDGET_SECONDS = 50.0
NEW_AGENT_DAYS = 7           # as routers/media.py: younger authors' thumbnails wait

MAX_TITLE = 200
MAX_DESCRIPTION = 500
MAX_SITE_NAME = 200
MAX_URL = safe_fetch.MAX_URL_LENGTH
MAX_TAGS = 5000              # start tags parsed before giving up on the head
MAX_ATTR_CHARS = 4096        # of any one attribute value
MAX_TITLE_CHARS = 2000       # <title> text collected
_CHARSET_SNIFF_BYTES = 4096

# The sentinel card for "looked at, no link": sha256 of the empty string.
NO_LINK_KEY = hashlib.sha256(b"").hexdigest()

Fetcher = Callable[..., Awaitable[safe_fetch.Fetched]]


# ── Which link ───────────────────────────────────────────────────────────────

_URL_RE = re.compile(r'https?://[^\s<>"]+')
_TRAILING = ".,;:!?)]}'"
_HAS_HOST = re.compile(r"^https?://[^/?#]", re.IGNORECASE)


def first_url(text: Optional[str]) -> Optional[str]:
    """The first link in *text* by the UI's rules, or None."""
    if not text:
        return None
    for m in _URL_RE.finditer(text):
        href = m.group(0).rstrip(_TRAILING)
        if _HAS_HOST.match(href):
            return href
    return None


def normalise(url: str) -> str:
    """Lowercase scheme and host (IDNA), no default port, no fragment, ``/``
    for an empty path. A URL the guard cannot parse is kept as written, minus
    its fragment (its card will be ``FAILED``)."""
    try:
        return safe_fetch.check_url(url, blocked_hosts=()).url[:MAX_URL]
    except safe_fetch.FetchRefused:
        return url.split("#", 1)[0][:MAX_URL]


def url_key(normalised: str) -> str:
    return hashlib.sha256(normalised.encode("utf-8", "surrogatepass")).hexdigest()


# ── Parsing ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CardMeta:
    title: Optional[str] = None
    description: Optional[str] = None
    site_name: Optional[str] = None
    image_url: Optional[str] = None

    @property
    def empty(self) -> bool:
        return not (self.title or self.description)


_CHARSET_RE = re.compile(rb"""charset\s*=\s*["']?\s*([A-Za-z0-9_.:\-]{1,40})""", re.IGNORECASE)
_BOMS = ((codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"),
         (codecs.BOM_UTF16_BE, "utf-16-be"))


def decode_html(data: bytes) -> str:
    """BOM, then a ``charset=`` in the first 4 KiB, then UTF-8; never raises."""
    for bom, enc in _BOMS:
        if data.startswith(bom):
            return data[len(bom):].decode(enc, errors="replace")
    m = _CHARSET_RE.search(data[:_CHARSET_SNIFF_BYTES])
    if m:
        try:
            name = codecs.lookup(m.group(1).decode("ascii")).name
            # Only real text encodings; utf-7 can hide markup from a reader.
            if name not in ("utf-7",) and not name.startswith("utf-16") and not name.startswith("utf-32"):
                return data.decode(name, errors="replace")
        except (LookupError, ValueError, TypeError):
            pass
    return data.decode("utf-8", errors="replace")


# Removed from card text: control characters and invisible format characters
# (bidi overrides, zero-width joiners), which can disguise text.
def clean_text(value: Optional[str], limit: int) -> Optional[str]:
    if not value:
        return None
    out = []
    for ch in value:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Cs", "Co", "Cn"):
            out.append(" " if ch in "\t\n\r\f\v" else "")
        else:
            out.append(ch)
    text = " ".join("".join(out).split())
    if not text:
        return None
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


class _Stop(Exception):
    pass


_TITLE_KEYS = ("og:title", "twitter:title")
_DESC_KEYS = ("og:description", "twitter:description", "description")
_SITE_KEYS = ("og:site_name",)
_IMAGE_KEYS = ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src")
_WANTED = frozenset(_TITLE_KEYS + _DESC_KEYS + _SITE_KEYS + _IMAGE_KEYS)


class _HeadParser(HTMLParser):
    """Collects ``<meta>`` and ``<title>`` until ``<body>`` (or a cap)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.title_len = 0
        self.in_title = False
        self.tags = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self.tags += 1
        if self.tags > MAX_TAGS or tag == "body":
            raise _Stop
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            key = content = None
            for name, value in attrs:
                if value is None:
                    continue
                if name in ("property", "name") and key is None:
                    k = value[:64].strip().lower()
                    if k in _WANTED:
                        key = k
                elif name == "content":
                    content = value[:MAX_ATTR_CHARS]
            if key and content is not None and key not in self.meta:
                self.meta[key] = content

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag == "head":
            raise _Stop

    def handle_data(self, data: str) -> None:
        if self.in_title and self.title_len < MAX_TITLE_CHARS:
            piece = data[: MAX_TITLE_CHARS - self.title_len]
            self.title_parts.append(piece)
            self.title_len += len(piece)


def _first(meta: dict[str, str], keys: Iterable[str]) -> Optional[str]:
    for k in keys:
        if meta.get(k, "").strip():
            return meta[k]
    return None


def image_url(value: Optional[str], base_url: str) -> Optional[str]:
    """An absolute http(s) URL for the card image, or None."""
    if not value:
        return None
    value = value.strip()
    if not value or any(ord(c) < 0x20 or c == "\x7f" for c in value):
        return None
    try:
        absolute = urljoin(base_url, value)
        scheme = urlsplit(absolute).scheme.lower()
    except ValueError:
        return None
    if scheme not in ("http", "https") or len(absolute) > MAX_URL:
        return None
    return absolute


def parse_card(data: bytes | str, base_url: str) -> CardMeta:
    """Read the card fields from (the head of) an HTML page. Plain text only;
    never raises for any input."""
    text = data if isinstance(data, str) else decode_html(data)
    parser = _HeadParser()
    try:
        parser.feed(text)
        parser.close()
    except _Stop:
        pass
    except Exception:   # noqa: BLE001 — a page that breaks the parser gets no more fields
        logger.debug("link_cards: parser stopped on malformed HTML", exc_info=True)
    meta = parser.meta
    title = _first(meta, _TITLE_KEYS) or "".join(parser.title_parts)
    return CardMeta(
        title=clean_text(title, MAX_TITLE),
        description=clean_text(_first(meta, _DESC_KEYS), MAX_DESCRIPTION),
        site_name=clean_text(_first(meta, _SITE_KEYS), MAX_SITE_NAME),
        image_url=image_url(_first(meta, _IMAGE_KEYS), base_url),
    )


# ── The job ──────────────────────────────────────────────────────────────────

def link_cards_enabled(settings=None) -> bool:
    """True only for LINK_CARDS_ENABLED in {1, true, yes} (any case)."""
    settings = settings or get_settings()
    return str(getattr(settings, "link_cards_enabled", "") or "").strip().lower() in _TRUE


_CANDIDATES = """
    SELECT p.post_id, p.author_did, p.content,
           a.created_at > NOW() - make_interval(days => $3) AS author_is_new
      FROM posts p
      JOIN agents a ON a.agent_did = p.author_did
     WHERE p.link_url_key IS NULL
       AND p.hidden_at IS NULL
       AND p.visibility = 'PUBLIC'
       AND p.created_at > NOW() - make_interval(hours => $2)
       AND p.content ~ 'https?://'
     ORDER BY p.created_at
     LIMIT $1
"""
_FRESH = """
    SELECT url_key FROM link_cards
     WHERE url_key = ANY($1::text[])
       AND fetched_at > NOW() - make_interval(hours => $2)
"""
_UPSERT = """
    INSERT INTO link_cards (url_key, url, title, description, site_name,
                            thumb_media_id, status, fetched_at)
    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
    ON CONFLICT (url_key) DO UPDATE
       SET url = EXCLUDED.url, title = EXCLUDED.title,
           description = EXCLUDED.description, site_name = EXCLUDED.site_name,
           thumb_media_id = EXCLUDED.thumb_media_id, status = EXCLUDED.status,
           fetched_at = EXCLUDED.fetched_at
"""
_LINK = """
    UPDATE posts SET link_url_key = $1
     WHERE post_id = ANY($2::uuid[]) AND link_url_key IS NULL
"""
_NO_LINK_ROW = """
    INSERT INTO link_cards (url_key, url, status) VALUES ($1, '', 'FAILED')
    ON CONFLICT (url_key) DO NOTHING
"""


@dataclass
class _Group:
    url: str
    post_ids: list
    owner_did: str          # author of the first post: owns the thumbnail
    owner_is_new: bool


async def _make_thumb(fetcher: Fetcher, src: str, group: _Group) -> Optional[tuple[UUID, str]]:
    """Fetch, rebuild and store the card image; (media_id, ext) or None."""
    try:
        got = await fetcher(src, "image")
    except safe_fetch.FetchRefused as exc:
        logger.info("link_cards: no image (%s)", exc.code)
        return None
    try:
        processed = await asyncio.to_thread(media_images.process, got.data)
    except media_images.ImageRefused as exc:
        logger.info("link_cards: image refused (%s)", exc.code)
        return None
    settings = get_settings()
    root = settings.media_root
    try:
        if media_store.free_bytes(root) < settings.media_min_free_bytes:
            logger.warning("link_cards: media disk nearly full; card without image")
            return None
        media_id = uuid4()
        media_store.write(root, media_id, processed.ext, processed.data)
    except OSError:
        logger.exception("link_cards: could not store the image")
        return None
    status = "PENDING" if group.owner_is_new else "APPROVED"
    try:
        async with transaction() as conn:
            await conn.execute(
                """
                INSERT INTO media (id, owner_did, kind, mime, ext, width, height,
                                   bytes, sha256, alt_text, status)
                VALUES ($1, $2, 'LINK_THUMB', $3, $4, $5, $6, $7, $8, '', $9)
                """,
                media_id, group.owner_did, processed.mime, processed.ext,
                processed.width, processed.height, processed.size, processed.sha256, status,
            )
    except BaseException:
        media_store.delete(root, media_id, processed.ext)
        raise
    return media_id, processed.ext


async def _fetch_card(fetcher: Fetcher, key: str, group: _Group) -> str:
    """Fetch one URL, store its card (OK or FAILED) and link its posts."""
    meta: Optional[CardMeta] = None
    thumb: Optional[tuple[UUID, str]] = None
    try:
        page = await fetcher(group.url, "html")
        meta = parse_card(page.data, page.url)
        if meta.empty:
            meta = None
        elif meta.image_url:
            thumb = await _make_thumb(fetcher, meta.image_url, group)
    except safe_fetch.FetchRefused as exc:
        logger.info("link_cards: no card (%s)", exc.code)
    try:
        async with transaction() as conn:
            await conn.execute(
                _UPSERT, key, group.url,
                meta.title if meta else None,
                meta.description if meta else None,
                meta.site_name if meta else None,
                thumb[0] if thumb else None,
                "OK" if meta else "FAILED",
            )
            await conn.execute(_LINK, key, group.post_ids)
    except BaseException:
        if thumb:
            # The row is gone with the rollback; the file must go too.
            media_store.delete(get_settings().media_root, thumb[0], thumb[1])
        raise
    return "ok" if meta else "failed"


async def run_link_cards(*, fetcher: Fetcher = safe_fetch.fetch, settings=None) -> dict:
    """One run of the job. Returns counts for the scheduler's record."""
    summary: dict[str, Any] = {"enabled": False, "posts": 0, "cached": 0, "no_link": 0,
                               "fetched": 0, "ok": 0, "failed": 0, "deferred": 0}
    if not link_cards_enabled(settings):
        summary["skipped"] = "disabled"
        return summary
    summary["enabled"] = True

    async with transaction() as conn:
        rows = await conn.fetch(_CANDIDATES, CANDIDATES_PER_RUN, LOOKBACK_HOURS, NEW_AGENT_DAYS)
    summary["posts"] = len(rows)
    if not rows:
        return summary

    groups: dict[str, _Group] = {}
    no_link: list = []
    for r in rows:
        raw = first_url(r["content"])
        if raw is None:
            no_link.append(r["post_id"])
            continue
        url = normalise(raw)
        key = url_key(url)
        g = groups.get(key)
        if g is None:
            groups[key] = _Group(url, [r["post_id"]], r["author_did"], bool(r["author_is_new"]))
        else:
            g.post_ids.append(r["post_id"])

    async with transaction() as conn:
        if no_link:
            await conn.execute(_NO_LINK_ROW, NO_LINK_KEY)
            await conn.execute(_LINK, NO_LINK_KEY, no_link)
            summary["no_link"] = len(no_link)
        fresh = {r["url_key"] for r in await conn.fetch(_FRESH, list(groups), CACHE_HOURS)}
        for key in fresh:
            await conn.execute(_LINK, key, groups[key].post_ids)
            summary["cached"] += len(groups[key].post_ids)

    to_fetch = [(k, g) for k, g in groups.items() if k not in fresh]
    summary["deferred"] = max(0, len(to_fetch) - FETCHES_PER_RUN)
    to_fetch = to_fetch[:FETCHES_PER_RUN]
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(key: str, group: _Group) -> None:
        async with gate:
            summary["fetched"] += 1
            try:
                summary[await _fetch_card(fetcher, key, group)] += 1
            except Exception:   # noqa: BLE001 — one URL never stops the others
                logger.exception("link_cards: storing the card failed")

    try:
        async with asyncio.timeout(RUN_BUDGET_SECONDS):
            await asyncio.gather(*(one(k, g) for k, g in to_fetch))
    except TimeoutError:
        logger.warning("link_cards: run budget used up; the rest waits for the next run")
    logger.info("link_cards: %s", summary)
    return summary


# ── Reading ──────────────────────────────────────────────────────────────────

async def annotate(conn, posts: Iterable) -> None:
    """Fill ``link_card`` on PostResponse objects (one query per page).
    No card on a hidden post, for a failed fetch, or for the no-link marker;
    the image only once it is APPROVED."""
    from ..models.post import LinkCard, LinkCardImage
    from .post_media import media_url

    posts = list(posts)
    if not posts:
        return
    rows = await conn.fetch(
        """
        SELECT p.post_id, c.url, c.title, c.description, c.site_name,
               m.id AS media_id, m.ext, m.width, m.height
          FROM posts p
          JOIN link_cards c ON c.url_key = p.link_url_key AND c.status = 'OK'
          LEFT JOIN media m ON m.id = c.thumb_media_id AND m.status = 'APPROVED'
         WHERE p.post_id = ANY($1::uuid[]) AND p.hidden_at IS NULL
        """,
        list({p.post_id for p in posts}),
    )
    by_post = {}
    for r in rows:
        image = None
        if r["media_id"] is not None:
            image = LinkCardImage(url=media_url(r["media_id"], r["ext"]),
                                  width=r["width"], height=r["height"])
        by_post[r["post_id"]] = LinkCard(
            url=r["url"], title=r["title"], description=r["description"],
            site_name=r["site_name"], image=image,
        )
    for p in posts:
        p.link_card = None if getattr(p, "hidden", False) else by_post.get(p.post_id)
