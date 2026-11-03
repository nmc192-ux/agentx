"""
AgentX Platform — Media cleanup job (Layer 1, S4-8)
═══════════════════════════════════════════════════
Runs every hour while images or link cards are switched on
(MEDIA_ENABLED or LINK_CARDS_ENABLED). One run, in this order:

  1. **Unattached uploads.** An `UPLOAD` row with no post, older than
     24 h, is deleted, and then its file. Rows are taken `FOR UPDATE SKIP
     LOCKED`, the same lock a post takes when it attaches them, so an image
     being attached right now is left for the next run.
  2. **Old link cards.** A card fetched more than 30 days ago that no post
     points at is deleted (never the "no link" marker card).
  3. **Unused link thumbnails.** A `LINK_THUMB` row older than 24 h that no
     link card points at (its card was deleted, or a refresh gave the card a
     new image) is deleted, and then its file.
  4. **Disk sweep.** Every `{MEDIA_ROOT}/{xx}/{uuid}.{ext}` file older than
     an hour is checked against the table: a file with no row, a file whose
     row says another extension, and the file of a `REJECTED` row are
     deleted. Leftover `.upload-*.tmp` files older than an hour go too.
     Anything else in the folder is left alone. Symlinks are never followed.

What it never touches: an `APPROVED` or `PENDING` image on a post, an image
a card still shows, any file younger than an hour (an upload writes its file
just before its row), and anything outside MEDIA_ROOT.

Files are deleted only after the row's delete has committed. If a file
delete fails, the next sweep finds it as a file with no row.

If MEDIA_ROOT does not exist the run does nothing and says so (rows are
never deleted when their files cannot be): a scheduler without the media
volume must not leave files behind on the API's disk.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

from ..config import get_settings
from ..database import transaction
from ..services import media_store
from ..services.link_cards import NO_LINK_KEY

logger = logging.getLogger("agentx.media_cleanup")

UNATTACHED_HOURS = 24
CARD_UNUSED_DAYS = 30
THUMB_GRACE_HOURS = 24
FILE_GRACE_SECONDS = 3600
BATCH = 500                 # rows per delete, ids per lookup
MAX_ROWS_PER_RUN = 5000     # per row rule; the rest waits for the next run

_TRUE = frozenset({"1", "true", "yes"})
_FILE_RE = re.compile(
    r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.(jpg|png|webp|gif)$")
_TMP_RE = re.compile(r"^\.upload-.*\.tmp$")
_DIR_RE = re.compile(r"^[0-9a-f]{2}$")

_UNATTACHED = """
    DELETE FROM media WHERE id IN (
        SELECT id FROM media
         WHERE kind = 'UPLOAD' AND post_id IS NULL
           AND created_at < NOW() - make_interval(hours => $1)
         ORDER BY created_at
         LIMIT $2
           FOR UPDATE SKIP LOCKED)
    RETURNING id, ext
"""
_OLD_CARDS = """
    DELETE FROM link_cards WHERE url_key IN (
        SELECT c.url_key FROM link_cards c
         WHERE c.url_key <> $3
           AND c.fetched_at < NOW() - make_interval(days => $1)
           AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.link_url_key = c.url_key)
         LIMIT $2
           FOR UPDATE SKIP LOCKED)
    RETURNING url_key
"""
_UNUSED_THUMBS = """
    DELETE FROM media WHERE id IN (
        SELECT m.id FROM media m
         WHERE m.kind = 'LINK_THUMB' AND m.post_id IS NULL
           AND m.created_at < NOW() - make_interval(hours => $1)
           AND NOT EXISTS (SELECT 1 FROM link_cards c WHERE c.thumb_media_id = m.id)
         ORDER BY m.created_at
         LIMIT $2
           FOR UPDATE SKIP LOCKED)
    RETURNING id, ext
"""
_ROWS_FOR = "SELECT id, ext, status FROM media WHERE id = ANY($1::uuid[])"


def cleanup_enabled(settings=None) -> bool:
    """On while either images or link cards are switched on."""
    settings = settings or get_settings()
    return any(
        str(getattr(settings, name, "") or "").strip().lower() in _TRUE
        for name in ("media_enabled", "link_cards_enabled"))


async def _delete_rows(sql: str, *args) -> list[tuple[UUID, str]]:
    """Run a batched DELETE … RETURNING id, ext until done or capped."""
    gone: list[tuple[UUID, str]] = []
    while len(gone) < MAX_ROWS_PER_RUN:
        async with transaction() as conn:
            rows = await conn.fetch(sql, *args, min(BATCH, MAX_ROWS_PER_RUN - len(gone)))
        gone.extend((r["id"], r["ext"]) for r in rows)
        if len(rows) < BATCH:
            break
    return gone


def _remove_files(root: Path, rows: list[tuple[UUID, str]]) -> int:
    removed = 0
    for media_id, ext in rows:
        try:
            removed += media_store.delete(root, media_id, ext)
        except OSError:
            logger.exception("media_cleanup: could not delete a file (next sweep retries)")
    return removed


def _old_enough(entry: os.DirEntry, now: float) -> bool:
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return False
    return now - st.st_mtime >= FILE_GRACE_SECONDS


def _scan(root: Path, now: float) -> Iterator[tuple[str, Any]]:
    """Yield ("tmp", path) and ("file", (path, UUID, ext)) for regular files
    old enough to judge. Only two-hex-digit folders directly under root."""
    with os.scandir(root) as top:
        folders = [e for e in top
                   if _DIR_RE.match(e.name) and e.is_dir(follow_symlinks=False)]
    for folder in folders:
        try:
            with os.scandir(folder.path) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            if not e.is_file(follow_symlinks=False) or not _old_enough(e, now):
                continue
            if _TMP_RE.match(e.name):
                yield "tmp", Path(e.path)
                continue
            m = _FILE_RE.match(e.name)
            if m is None:
                continue
            media_id = UUID(m.group(1))
            if media_id.hex[:2] != folder.name:
                continue    # not where we put it: not ours to judge
            yield "file", (Path(e.path), media_id, m.group(2))


def _unlink(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        logger.exception("media_cleanup: could not delete a file")
        return False


async def _sweep(root: Path, summary: dict) -> None:
    now = time.time()
    pending: list[tuple[Path, UUID, str]] = []

    async def judge() -> None:
        async with transaction() as conn:
            rows = await conn.fetch(_ROWS_FOR, [p[1] for p in pending])
        known = {r["id"]: (r["ext"], r["status"]) for r in rows}
        for path, media_id, ext in pending:
            row = known.get(media_id)
            if row is None or row[0] != ext:
                summary["orphan_files"] += _unlink(path)
            elif row[1] == "REJECTED":
                summary["rejected_files"] += _unlink(path)
        pending.clear()

    for kind, item in _scan(root, now):
        if kind == "tmp":
            summary["temp_files"] += _unlink(item)
            continue
        summary["files_checked"] += 1
        pending.append(item)
        if len(pending) >= BATCH:
            await judge()
    if pending:
        await judge()


async def run_media_cleanup(*, settings=None) -> dict:
    """One run of the job. Returns counts for the scheduler's record."""
    settings = settings or get_settings()
    summary: dict[str, Any] = {
        "unattached": 0, "old_cards": 0, "unused_thumbs": 0, "files_deleted": 0,
        "files_checked": 0, "orphan_files": 0, "rejected_files": 0, "temp_files": 0,
    }
    if not cleanup_enabled(settings):
        summary["skipped"] = "disabled"
        return summary
    root = Path(settings.media_root)
    if not root.is_dir() or root.is_symlink():
        logger.warning("media_cleanup: MEDIA_ROOT is not a folder here; nothing done")
        summary["skipped"] = "no_media_root"
        return summary

    gone = await _delete_rows(_UNATTACHED, UNATTACHED_HOURS)
    summary["unattached"] = len(gone)
    summary["files_deleted"] += _remove_files(root, gone)

    async with transaction() as conn:
        cards = await conn.fetch(_OLD_CARDS, CARD_UNUSED_DAYS, MAX_ROWS_PER_RUN, NO_LINK_KEY)
    summary["old_cards"] = len(cards)

    gone = await _delete_rows(_UNUSED_THUMBS, THUMB_GRACE_HOURS)
    summary["unused_thumbs"] = len(gone)
    summary["files_deleted"] += _remove_files(root, gone)

    await _sweep(root, summary)
    logger.info("media_cleanup: %s", summary)
    return summary
