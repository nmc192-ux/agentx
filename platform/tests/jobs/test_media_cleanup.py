"""
Layer 1 S4-8: the media cleanup job without a database (switch, missing
folder, what the disk scan is allowed to look at). The deletes themselves are
tested on real Postgres in tests/integration/test_media_cleanup_db.py.
"""
import os
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.jobs import media_cleanup as mc
from src.jobs.scheduler import JOBS


def _settings(media="false", cards="false", root="/nonexistent-media-root"):
    return SimpleNamespace(media_enabled=media, link_cards_enabled=cards, media_root=root)


@pytest.mark.parametrize("media,cards,on", [
    ("false", "false", False), ("", "", False), ("0", "no", False), ("TRUE-ish", "off", False),
    ("true", "false", True), ("false", "1", True), ("YES", "", True), (" true ", "true", True),
])
def test_switch(media, cards, on):
    assert mc.cleanup_enabled(_settings(media, cards)) is on


def test_scheduler_entry():
    entry = {j.name: j for j in JOBS}["media_cleanup"]
    assert entry.interval == 3600.0
    assert entry.run is mc.run_media_cleanup
    assert entry.enabled is mc.cleanup_enabled


def test_constants():
    assert mc.UNATTACHED_HOURS == 24 and mc.CARD_UNUSED_DAYS == 30
    assert mc.FILE_GRACE_SECONDS == 3600 and mc.THUMB_GRACE_HOURS == 24


async def test_off_touches_nothing(tmp_path):
    (tmp_path / "x").write_text("keep")
    summary = await mc.run_media_cleanup(settings=_settings(root=str(tmp_path)))
    assert summary["skipped"] == "disabled"
    assert (tmp_path / "x").exists()


async def test_missing_root_does_nothing():
    # No database is set up here: reaching a query would raise.
    summary = await mc.run_media_cleanup(settings=_settings(media="true"))
    assert summary["skipped"] == "no_media_root"


async def test_symlinked_root_does_nothing(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    summary = await mc.run_media_cleanup(settings=_settings(media="true", root=str(link)))
    assert summary["skipped"] == "no_media_root"


def _old(path):
    t = time.time() - 2 * 3600
    os.utime(path, (t, t), follow_symlinks=False)


def test_scan_sees_only_old_regular_files_in_place(tmp_path):
    good = uuid4()
    d = tmp_path / good.hex[:2]
    d.mkdir()
    ours = d / f"{good}.png"
    ours.write_bytes(b"x")
    _old(ours)
    young_id = uuid4()
    (tmp_path / young_id.hex[:2]).mkdir(exist_ok=True)
    young = tmp_path / young_id.hex[:2] / f"{young_id}.jpg"
    young.write_bytes(b"x")                                   # under an hour old
    tmp = d / ".upload-abc.tmp"
    tmp.write_bytes(b"x")
    _old(tmp)
    young_tmp = d / ".upload-new.tmp"
    young_tmp.write_bytes(b"x")
    misplaced_id = uuid4()
    wrong = tmp_path / ("00" if misplaced_id.hex[:2] != "00" else "01")
    wrong.mkdir(exist_ok=True)
    misplaced = wrong / f"{misplaced_id}.png"
    misplaced.write_bytes(b"x")
    _old(misplaced)
    for name in ("notes.txt", f"{uuid4()}.html", f"{uuid4()}.PNG", f"{str(uuid4()).upper()}.png"):
        p = d / name
        p.write_bytes(b"x")
        _old(p)
    outside = tmp_path.parent / f"outside-{uuid4().hex}"
    outside.mkdir()
    target = outside / "secret.png"
    target.write_bytes(b"x")
    _old(target)
    link_id = uuid4()
    link_dir = tmp_path / link_id.hex[:2]
    link_dir.mkdir(exist_ok=True)
    link = link_dir / f"{link_id}.png"
    link.symlink_to(target)
    _old(link)
    (tmp_path / "zz").mkdir()                            # not a hex folder
    top_file = tmp_path / f"{uuid4()}.png"                    # not in a folder
    top_file.write_bytes(b"x")
    _old(top_file)
    dir_link = tmp_path / "ab"
    if not dir_link.exists():
        dir_link.symlink_to(outside, target_is_directory=True)

    seen = list(mc._scan(tmp_path, time.time()))
    assert ("tmp", tmp) in seen
    files = [item for kind, item in seen if kind == "file"]
    assert files == [(ours, good, "png")]
    assert len(seen) == 2


def test_unlink_tolerates_missing(tmp_path):
    assert mc._unlink(tmp_path / "gone.png") is False
