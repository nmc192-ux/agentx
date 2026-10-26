"""
Unit tests: BRUNO and QUINN ops facts (src/founders/ops_facts.py, TF-3).

What is proven (no database: a fake connection and a temporary status folder):
  • each record the VPS scripts write becomes one plain sentence holding its
    numbers, and every sentence passes the TF-1 claim checker against itself
  • a missing, garbled, non-object, oversized, undated, future-dated or
    week-old record is no fact
  • a release or CI record for another commit than the live one is no fact;
    without a known live commit there is no release, commit or CI fact
  • CI with checks still running, or with no checks, is no fact
  • scheduled jobs: all ok → one "all ended without an error" fact; failures
    are counted and named; no runs or a failed query → no fact
  • read_facts dispatches "bruno" and "quinn" to these readers
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from src.founders import facts as F
from src.founders import ops_facts as O
from src.founders.truth import claim_problems

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
SHA = "1a2b3c4d" + "e" * 32
OTHER = "f" * 40
_TAG = re.compile(r"/\* fact:([a-z_.]+) \*/")


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, rows=None, fail=()):
        self.rows, self.fail = dict(rows or {}), set(fail)

    def transaction(self):
        return _Tx()

    async def fetchrow(self, sql, *args):
        name = _TAG.search(sql).group(1)
        if name in self.fail:
            raise RuntimeError("broken")
        return self.rows.get(name)


def _iso(delta: timedelta) -> str:
    return (NOW - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def status(tmp_path, monkeypatch):
    monkeypatch.setattr(O.get_settings(), "founder_status_dir", str(tmp_path))
    monkeypatch.setattr(O.get_settings(), "git_commit", SHA)

    def write(name, data):
        (tmp_path / f"{name}.json").write_text(data if isinstance(data, str) else json.dumps(data))
    return write


def _check(facts):
    for f in facts:
        assert claim_problems(f.text, facts=[f.text]) == [], (f.key, f.text)
        assert f.as_of == NOW and f.source.startswith(("db:", "code:", "file:"))


def _keys(facts):
    return {f.key: f.text for f in facts}


ALL_OK = {"bruno.jobs": {"ok": 4, "failed": 0, "failed_names": []}}


# ── BRUNO ────────────────────────────────────────────────────────────────────

async def test_bruno_full(status):
    status("deploy", {"commit": SHA, "previous": OTHER, "finished_at": _iso(timedelta(hours=3)),
                      "migrated": True})
    status("backup", {"ok": True, "finished_at": _iso(timedelta(hours=10))})
    status("restore_test", {"ok": True, "finished_at": _iso(timedelta(hours=9))})
    facts = await O.bruno_facts(FakeConn(ALL_OK), NOW)
    _check(facts)
    k = _keys(facts)
    assert k["bruno.release"] == ("The platform runs commit 1a2b3c4, live since a release on "
                                  "18 Oct at 09:00 UTC, about 3 hours ago.")
    assert k["bruno.jobs_24h"] == ("All 4 scheduled jobs that ran in the last 24 hours ended "
                                   "without an error on their last run.")
    assert k["bruno.backup"] == "The newest nightly database backup finished on 18 Oct at 02:00 UTC."
    assert "tables matched, on 18 Oct at 03:00 UTC" in k["bruno.restore_drill"]


async def test_bruno_failed_jobs_and_drill(status):
    status("restore_test", {"ok": False, "finished_at": _iso(timedelta(hours=9))})
    rows = {"bruno.jobs": {"ok": 2, "failed": 2,
                           "failed_names": ["agent_of_week", "founder_heartbeat"]}}
    facts = await O.bruno_facts(FakeConn(rows), NOW)
    _check(facts)
    k = _keys(facts)
    assert k["bruno.jobs_24h"] == ("Of 4 scheduled jobs that ran in the last 24 hours, 2 ended in "
                                   "an error on their last run: agent of week, founder heartbeat.")
    assert "could not load" in k["bruno.restore_drill"]
    # No deploy record → only the commit this process runs.
    assert k["bruno.commit"] == "The platform runs commit 1a2b3c4."


async def test_bruno_job_names_with_digits_are_not_named(status):
    rows = {"bruno.jobs": {"ok": 0, "failed": 1, "failed_names": ["job2"]}}
    k = _keys(await O.bruno_facts(FakeConn(rows), NOW))
    assert k["bruno.jobs_24h"].endswith("1 ended in an error on its last run.")


@pytest.mark.parametrize("rows,fail", [
    ({}, ()),
    ({"bruno.jobs": {"ok": 0, "failed": 0, "failed_names": []}}, ()),
    (ALL_OK, ("bruno.jobs",)),
])
async def test_bruno_no_job_fact(status, rows, fail):
    assert "bruno.jobs_24h" not in _keys(await O.bruno_facts(FakeConn(rows, fail), NOW))


async def test_release_for_another_commit_is_no_fact(status):
    status("deploy", {"commit": OTHER, "finished_at": _iso(timedelta(hours=1))})
    k = _keys(await O.bruno_facts(FakeConn(), NOW))
    assert "bruno.release" not in k and "bruno.commit" in k


async def test_unknown_live_commit_gives_no_commit_facts(status, monkeypatch):
    monkeypatch.setattr(O.get_settings(), "git_commit", "unknown")
    status("deploy", {"commit": SHA, "finished_at": _iso(timedelta(hours=1))})
    status("ci", {"commit": SHA, "checked_at": _iso(timedelta(hours=1)),
                  "total": 3, "failed": 0, "pending": 0})
    assert await O.bruno_facts(FakeConn(), NOW) == []
    assert await O.quinn_facts(FakeConn(), NOW) == []


@pytest.mark.parametrize("record", [
    "not json",
    "[1, 2]",
    json.dumps({"ok": True}),                                          # undated
    json.dumps({"ok": True, "finished_at": "yesterday"}),
    json.dumps({"ok": True, "finished_at": "2026-10-18T02:00:00"}),    # no time zone
    json.dumps({"ok": True, "finished_at": _iso(timedelta(days=8))}),  # stale
    json.dumps({"ok": True, "finished_at": _iso(-timedelta(hours=1))}),  # future
    json.dumps({"ok": "yes", "finished_at": _iso(timedelta(hours=1))}),
    json.dumps({"ok": True, "finished_at": _iso(timedelta(hours=1)), "pad": "x" * 70000}),
])
async def test_bad_backup_record_is_no_fact(status, record):
    status("backup", record)
    status("restore_test", record)
    k = _keys(await O.bruno_facts(FakeConn(), NOW))
    assert "bruno.backup" not in k and "bruno.restore_drill" not in k


async def test_missing_folder_is_no_fact(monkeypatch, tmp_path):
    monkeypatch.setattr(O.get_settings(), "founder_status_dir", str(tmp_path / "absent"))
    monkeypatch.setattr(O.get_settings(), "git_commit", SHA)
    assert set(_keys(await O.bruno_facts(FakeConn(), NOW))) == {"bruno.commit"}
    assert await O.quinn_facts(FakeConn(), NOW) == []


def test_read_status_on_a_directory_named_like_a_record(tmp_path):
    (tmp_path / "smoke.json").mkdir()
    assert O.read_status("smoke", NOW, str(tmp_path)) is None


# ── QUINN ────────────────────────────────────────────────────────────────────

async def test_quinn_full(status):
    status("smoke", {"finished_at": _iso(timedelta(hours=2)), "passed": 6, "failed": 0,
                     "skipped": 1})
    status("ci", {"commit": SHA, "checked_at": _iso(timedelta(hours=3)),
                  "total": 5, "failed": 0, "pending": 0})
    facts = await O.quinn_facts(FakeConn(), NOW)
    _check(facts)
    k = _keys(facts)
    assert k["quinn.smoke"] == ("The newest smoke run against the live API, on 18 Oct at "
                                "10:00 UTC, passed 6 of 7 checks (1 skipped).")
    assert k["quinn.ci"] == "CI for the live commit 1a2b3c4: all 5 checks passed."


async def test_quinn_failures_are_said(status):
    status("smoke", {"finished_at": _iso(timedelta(hours=2)), "passed": 5, "failed": 2,
                     "skipped": 0})
    status("ci", {"commit": SHA, "checked_at": _iso(timedelta(hours=3)),
                  "total": 5, "failed": 1, "pending": 0})
    facts = await O.quinn_facts(FakeConn(), NOW)
    _check(facts)
    k = _keys(facts)
    assert k["quinn.smoke"].endswith("passed 5 of 7 checks (2 failed).")
    assert k["quinn.ci"] == "CI for the live commit 1a2b3c4: 1 of 5 checks did not pass."


@pytest.mark.parametrize("ci", [
    {"commit": OTHER, "total": 5, "failed": 0, "pending": 0},
    {"commit": SHA, "total": 5, "failed": 0, "pending": 2},
    {"commit": SHA, "total": 0, "failed": 0, "pending": 0},
    {"commit": SHA, "total": 2, "failed": 3, "pending": 0},
    {"commit": SHA, "total": "5", "failed": 0, "pending": 0},
    {"commit": SHA, "total": True, "failed": 0, "pending": 0},
])
async def test_quinn_ci_not_a_fact(status, ci):
    status("ci", {**ci, "checked_at": _iso(timedelta(hours=1))})
    assert await O.quinn_facts(FakeConn(), NOW) == []


@pytest.mark.parametrize("smoke", [
    {"passed": 0, "failed": 0, "skipped": 3},
    {"passed": -1, "failed": 0, "skipped": 0},
    {"passed": 3, "failed": 0},
])
async def test_quinn_smoke_not_a_fact(status, smoke):
    status("smoke", {**smoke, "finished_at": _iso(timedelta(hours=1))})
    assert await O.quinn_facts(FakeConn(), NOW) == []


async def test_read_facts_dispatches_bruno_and_quinn(status):
    status("smoke", {"finished_at": _iso(timedelta(hours=2)), "passed": 1, "failed": 0,
                     "skipped": 0})
    assert {f.key for f in await F.read_facts(FakeConn(ALL_OK), "bruno", NOW)} == {
        "bruno.commit", "bruno.jobs_24h"}
    assert {f.key for f in await F.read_facts(FakeConn(), "quinn", NOW)} == {"quinn.smoke"}
