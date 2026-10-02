"""
Integration tests: scripts/moderate_posts.py against REAL local Postgres.
Sprint 9, S9-8c2.

What is proven:
  • scan: a dry run changes nothing; --apply holds the solicitation posts
    (title, content or tags) and only those, logging each; a second run is a
    no-op; a post a moderator cleared is not held again
  • hide / unhide: dry run changes nothing; --apply changes the post, logs
    the action under the given actor and dismisses flags on unhide;
    missing post → 404, hiding twice → 409, unhiding a clean post → 409
  • queue lists hidden and flagged posts
  • the command line runs end to end (dry run, then --apply)

Run: cd platform && .venv/bin/python -m pytest tests/integration -v --db
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from .conftest import PG_PORT, PG_USER, smoke

pytestmark = pytest.mark.integration   # skipped unless --db is given

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "moderate_posts.py"
_spec = importlib.util.spec_from_file_location("moderate_posts", _SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

# Not the wording test_post_moderation_db.py looks for in public lists: a post
# cleared here stays visible.
SOLICITATION = "Sign up with my referral link and get paid in USDT for every friend."


async def _insert(pool, author_did: str, content: str, title: str = "Update",
                  tags: list[str] | None = None) -> str:
    """Insert straight into the table, as posts made before migration 043 were:
    nothing has held them."""
    return await pool.fetchval(
        "INSERT INTO posts (author_did, post_type, title, content, tags) "
        "VALUES ($1, 'UPDATE', $2, $3, $4) RETURNING post_id",
        author_did, title, content, tags or [],
    )


async def _state(pool, post_id):
    return await pool.fetchrow(
        "SELECT hidden_at, hidden_reason, hidden_by, moderation_cleared_at "
        "FROM posts WHERE post_id = $1",
        post_id,
    )


async def _log(pool, post_id) -> list[tuple]:
    rows = await pool.fetch(
        "SELECT action, actor_did, reason, note FROM post_moderation_log "
        "WHERE post_id = $1 ORDER BY created_at",
        post_id,
    )
    return [tuple(r) for r in rows]


async def test_scan_dry_run_then_apply_holds_only_solicitations(pool, agents):
    alice = await agents("alice")
    advert = await _insert(pool, alice.did, SOLICITATION)
    in_title = await _insert(pool, alice.did, "details inside", title="Buy cheap followers now")
    in_tags = await _insert(pool, alice.did, "see tags", tags=["referral-link", "news"])
    clean = await _insert(pool, alice.did, "Bitcoin fell 3% today; commissions are a topic.")
    ours = {advert, in_title, in_tags}

    async with pool.acquire() as conn:
        found = {m["post_id"]: m["rule"] for m in await mod.scan(conn)}
        assert ours <= found.keys() and clean not in found
        assert found[advert] in ("referral", "commission")
        for pid in ours | {clean}:
            assert (await _state(pool, pid))["hidden_at"] is None     # dry run wrote nothing
            assert await _log(pool, pid) == []

        held = {m["post_id"] for m in await mod.scan(conn, apply=True)}
        assert ours <= held and clean not in held
        for pid in ours:
            st = await _state(pool, pid)
            assert st["hidden_at"] is not None
            assert st["hidden_reason"] == "auto_hold:solicitation"
            [(action, actor, reason, _)] = await _log(pool, pid)
            assert (action, actor, reason) == ("auto_hold", None, "auto_hold:solicitation")
        assert (await _state(pool, clean))["hidden_at"] is None

        again = {m["post_id"] for m in await mod.scan(conn, apply=True)}
        assert not (again & (ours | {clean}))
        for pid in ours:
            assert len(await _log(pool, pid)) == 1


async def test_scan_skips_a_post_a_moderator_cleared(pool, agents):
    alice = await agents("alice")
    advert = await _insert(pool, alice.did, SOLICITATION)
    async with pool.acquire() as conn:
        await mod.scan(conn, apply=True)
        await mod.unhide(conn, advert, note="false positive", by="did:agentx:drj", apply=True)
        st = await _state(pool, advert)
        assert st["hidden_at"] is None and st["moderation_cleared_at"] is not None
        assert advert not in {m["post_id"] for m in await mod.scan(conn, apply=True)}
    assert (await _state(pool, advert))["hidden_at"] is None
    assert [a for a, *_ in await _log(pool, advert)] == ["auto_hold", "unhide"]


async def test_hide_and_unhide_dry_run_then_apply(pool, agents):
    alice, bob = await agents("alice"), await agents("bob")
    post = await _insert(pool, alice.did, "an ordinary post")
    await pool.execute(
        "INSERT INTO post_flags (post_id, flagger_did, reason) VALUES ($1, $2, 'spam')",
        post, bob.did,
    )
    async with pool.acquire() as conn:
        row = await mod.hide(conn, post, "spam", note="n1")
        assert row["post_id"] == post
        assert (await _state(pool, post))["hidden_at"] is None
        assert await _log(pool, post) == []

        await mod.hide(conn, post, "spam", note="n1", by="did:agentx:drj", apply=True)
        st = await _state(pool, post)
        assert st["hidden_at"] is not None
        assert (st["hidden_reason"], st["hidden_by"]) == ("moderator:spam", "did:agentx:drj")

        with pytest.raises(HTTPException) as exc:
            await mod.hide(conn, post, "spam")
        assert exc.value.status_code == 409
        with pytest.raises(HTTPException) as exc:
            await mod.hide(conn, post, "spam", apply=True)
        assert exc.value.status_code == 409

        await mod.unhide(conn, post)                                     # dry run
        assert (await _state(pool, post))["hidden_at"] is not None

        await mod.unhide(conn, post, note="ok", apply=True)
        st = await _state(pool, post)
        assert st["hidden_at"] is None and st["moderation_cleared_at"] is not None
        queue = await mod.queue(conn, limit=500)
        assert post not in {p["post_id"] for p in queue["flagged"]["posts"]}

    assert await _log(pool, post) == [
        ("hide", "did:agentx:drj", "moderator:spam", "n1"),
        ("unhide", mod.DEFAULT_ACTOR, None, "ok"),
    ]


async def test_errors_change_nothing(pool, agents):
    alice = await agents("alice")
    clean = await _insert(pool, alice.did, "nothing to see")
    async with pool.acquire() as conn:
        for call in (
            mod.hide(conn, uuid4(), "spam", apply=True),
            mod.unhide(conn, uuid4(), apply=True),
        ):
            with pytest.raises(HTTPException) as exc:
                await call
            assert exc.value.status_code == 404
        for apply in (False, True):
            with pytest.raises(HTTPException) as exc:
                await mod.unhide(conn, clean, apply=apply)
            assert exc.value.status_code == 409
        with pytest.raises(HTTPException) as exc:
            await mod.hide(conn, clean, "rude", apply=True)
        assert exc.value.status_code == 422
    assert (await _state(pool, clean))["moderation_cleared_at"] is None
    assert await _log(pool, clean) == []


async def test_queue_lists_hidden_and_flagged(pool, agents):
    alice, bob = await agents("alice"), await agents("bob")
    hidden = await _insert(pool, alice.did, SOLICITATION)
    flagged = await _insert(pool, alice.did, "a flagged post")
    await pool.execute(
        "INSERT INTO post_flags (post_id, flagger_did, reason) VALUES ($1, $2, 'abuse')",
        flagged, bob.did,
    )
    async with pool.acquire() as conn:
        await mod.hide(conn, hidden, "solicitation", apply=True)
        queue = await mod.queue(conn, limit=500)
    assert hidden in {p["post_id"] for p in queue["hidden"]["posts"]}
    [f] = [p for p in queue["flagged"]["posts"] if p["post_id"] == flagged]
    assert f["flag_reasons"] == ["abuse"] and f["flag_count"] == 1


async def test_command_line_end_to_end(pool, agents, escrow_db):
    alice = await agents("alice")
    advert = await _insert(pool, alice.did, SOLICITATION)
    dsn = f"postgresql://{PG_USER}@{smoke.DB_HOST}:{PG_PORT}/{escrow_db}"

    def run(*argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), "--dsn", dsn, *argv],
            capture_output=True, text=True, timeout=60,
        )

    out = run("scan")
    assert out.returncode == 0, out.stderr
    assert str(advert) in out.stdout and "dry run" in out.stdout
    assert (await _state(pool, advert))["hidden_at"] is None

    out = run("scan", "--apply")
    assert out.returncode == 0, out.stderr
    assert (await _state(pool, advert))["hidden_at"] is not None

    out = run("queue", "--limit", "500")
    assert out.returncode == 0, out.stderr
    assert str(advert) in out.stdout

    out = run("unhide", str(advert), "--note", "checked", "--apply")
    assert out.returncode == 0, out.stderr
    assert (await _state(pool, advert))["hidden_at"] is None

    out = run("unhide", str(advert), "--apply")
    assert out.returncode == 1 and "Nothing done" in out.stderr

    out = run("hide", str(advert), "--reason", "solicitation")
    assert out.returncode == 0 and "Would hide" in out.stdout
    assert (await _state(pool, advert))["hidden_at"] is None
