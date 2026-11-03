"""
AgentX Platform — Media file store (Layer 1, S4-3)
═══════════════════════════════════════════════════
Where processed images live on disk. Files are named only from the media
row's UUID and its stored extension, never from anything a caller sent:

    {MEDIA_ROOT}/{first two hex digits of the id}/{id}.{ext}

The two-digit folder keeps any one directory small. Writes go to a temp file
in the same folder, are fsynced and then renamed into place, so a reader (the
other API copy shares the volume) never sees half a file. Deleting a file
that is already gone is not an error.

Pure file-system code: no database, no settings lookups (callers pass the
root), so the cleanup job (S4-8) can use it too.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from uuid import UUID

ALLOWED_EXTS = frozenset({"jpg", "png", "webp", "gif"})


def path_for(root: str | os.PathLike, media_id: UUID, ext: str) -> Path:
    """The file for *media_id*. Refuses anything but a UUID and a known ext."""
    if not isinstance(media_id, UUID):
        raise TypeError("media_id must be a UUID")
    if ext not in ALLOWED_EXTS:
        raise ValueError(f"unknown media extension: {ext!r}")
    hex_id = media_id.hex
    return Path(root) / hex_id[:2] / f"{media_id}.{ext}"


def write(root: str | os.PathLike, media_id: UUID, ext: str, data: bytes) -> Path:
    """Store *data* atomically; refuses to replace an existing file."""
    final = path_for(root, media_id, ext)
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise FileExistsError(str(final))
    fd, tmp = tempfile.mkstemp(prefix=".upload-", suffix=".tmp", dir=final.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, final)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return final


def delete(root: str | os.PathLike, media_id: UUID, ext: str) -> bool:
    """Remove the file; True if one was removed, False if it was not there."""
    try:
        path_for(root, media_id, ext).unlink()
        return True
    except FileNotFoundError:
        return False


def free_bytes(root: str | os.PathLike) -> int:
    """Free space on the disk holding *root* (its nearest existing parent)."""
    probe = Path(root)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free
