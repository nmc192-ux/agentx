"""Layer 1 S4-3: media file store (names come only from the UUID and ext)."""
import os
from uuid import UUID, uuid4

import pytest

from src.services import media_store


def test_path_is_built_from_uuid_and_ext_only(tmp_path):
    mid = UUID("abcdef01-2345-6789-abcd-ef0123456789")
    p = media_store.path_for(tmp_path, mid, "png")
    assert p == tmp_path / "ab" / "abcdef01-2345-6789-abcd-ef0123456789.png"


@pytest.mark.parametrize("bad", ["../etc/passwd", "abc", "", None, 123])
def test_non_uuid_id_refused(tmp_path, bad):
    with pytest.raises(TypeError):
        media_store.path_for(tmp_path, bad, "png")


@pytest.mark.parametrize("ext", ["html", "svg", "png/../x", "PNG", "", "jpeg"])
def test_unknown_ext_refused(tmp_path, ext):
    with pytest.raises(ValueError):
        media_store.path_for(tmp_path, uuid4(), ext)


def test_write_read_delete(tmp_path):
    mid = uuid4()
    p = media_store.write(tmp_path, mid, "jpg", b"data")
    assert p.read_bytes() == b"data"
    assert oct(os.stat(p).st_mode & 0o777) == "0o644"
    # No temp files left behind.
    assert sorted(x.name for x in p.parent.iterdir()) == [p.name]
    assert media_store.delete(tmp_path, mid, "jpg") is True
    assert media_store.delete(tmp_path, mid, "jpg") is False


def test_write_never_replaces(tmp_path):
    mid = uuid4()
    media_store.write(tmp_path, mid, "gif", b"one")
    with pytest.raises(FileExistsError):
        media_store.write(tmp_path, mid, "gif", b"two")
    assert media_store.path_for(tmp_path, mid, "gif").read_bytes() == b"one"


def test_failed_write_leaves_no_temp_file(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(media_store.os, "replace", boom)
    mid = uuid4()
    with pytest.raises(OSError):
        media_store.write(tmp_path, mid, "png", b"x")
    folder = tmp_path / mid.hex[:2]
    assert list(folder.iterdir()) == []


def test_free_bytes_walks_up_to_an_existing_folder(tmp_path):
    assert media_store.free_bytes(tmp_path / "not" / "there" / "yet") > 0
