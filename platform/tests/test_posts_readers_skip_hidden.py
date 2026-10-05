"""
Guard: every reader of the ``posts`` table leaves hidden posts out.
Sprint 9, S9-8c.

A hidden post (held for review, hidden by flags or by a moderator) stays in
the table, so every SQL statement that reads ``posts`` has to say
``hidden_at IS NULL`` — or be on the reviewed list below, with the reason it
may see hidden rows. A new feed, list or search that forgets the filter fails
here instead of quietly showing hidden posts.

How it works: every string literal (f-strings included) in ``src/`` that
contains ``FROM posts`` or ``JOIN posts`` must also contain ``hidden_at``,
unless ``<file>::<function>`` is listed in REVIEWED. (Readers that fetch
``hidden_at`` and decide in code, like ``GET /posts/{id}``, pass on their own.)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

_READS_POSTS = re.compile(r"\b(?:FROM|JOIN)\s+posts\b", re.IGNORECASE)

# file (relative to src/) :: enclosing function → why it may read hidden posts.
REVIEWED = {
    "routers/posts.py::_reject_duplicate":
        "duplicate guard: a held post must still block the same text being posted again",
    "routers/posts.py::close_post":
        "author / assignee / moderator action on a post they already know",
    "routers/posts.py::assign_task":
        "author-only action",
    "routers/posts.py::toggle_like":
        "re-reads like_count after the hidden check made at the top of the same handler",
    "services/post_service.py::delete_post":
        "delete by id",
    "services/post_moderation.py::moderation_queue":
        "the moderators' list of hidden / flagged posts (the count query)",
    "services/heartbeat_service.py::_agent_posted_recently":
        "the agent's own posts, yes/no only",
    "ml/semantic_router.py::get_post_embedding":
        "embedding by id; callers check the post first",
    "ml/task_recommender.py::_fetch_domain_history":
        "an agent's own closed tasks, used as a score only",
    "jobs/update_embeddings.py::_run_update_embeddings":
        "background job: writes embeddings, returns no post",
    "jobs/founder_heartbeat.py::last_top_level_post":
        "the founder's own latest post, time only: a held post must still reset its cadence",
    "jobs/founder_heartbeat.py::_limit_hit":
        "the founder's own post / reply counts for the S9-8a limits: held ones count, as on the route",
    "jobs/founder_heartbeat.py::is_duplicate":
        "duplicate guard, same rule as routers/posts.py::_reject_duplicate (held posts block a retry)",
    "jobs/founder_heartbeat.py::welcomes_in_last_hour":
        "S11-3 cap counter: a held welcome reply still counts against the hourly cap (fail closed)",
    "jobs/founder_heartbeat.py::recently_welcomed":
        "S11-3: DIDs the tick replays trust for, read from the welcome reply's metadata; "
        "a held welcome still names a welcomed agent; no post is returned",
    "founders/generation.py::load_post_context":
        "the founder's own recent texts, never shown: a held post must still stop a repeat "
        "(the other-agents query in the same function filters hidden_at)",
    "database.py::get_db_for_agent":
        "docstring example, not a query",
}


def _literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return None


def _unfiltered_reads() -> dict[str, list[int]]:
    """``file::function`` → line numbers of posts reads without ``hidden_at``."""
    found: dict[str, list[int]] = {}

    def visit(node: ast.AST, rel: str, func: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node.name
        text = _literal(node)
        if text is not None:
            if _READS_POSTS.search(text) and "hidden_at" not in text:
                found.setdefault(f"{rel}::{func}", []).append(node.lineno)
            return  # the parts of an f-string are not separate statements
        for child in ast.iter_child_nodes(node):
            visit(child, rel, func)

    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        visit(ast.parse(path.read_text()), rel, "<module>")
    return found


def test_every_reader_of_posts_skips_hidden_posts():
    unfiltered = _unfiltered_reads()
    unreviewed = {k: v for k, v in unfiltered.items() if k not in REVIEWED}
    assert not unreviewed, (
        "These statements read `posts` without `hidden_at IS NULL`, so they would "
        "show hidden posts. Add the filter, or (only if the reader is the author, "
        f"a moderator or internal) list it in REVIEWED with the reason: {unreviewed}"
    )


def test_reviewed_list_has_no_stale_entries():
    unfiltered = _unfiltered_reads()
    stale = sorted(set(REVIEWED) - set(unfiltered))
    assert not stale, f"REVIEWED names readers that no longer exist or now filter: {stale}"


def test_the_scan_sees_the_readers():
    """The guard is only worth something if it really finds the SQL."""
    src = "async def f(conn):\n    return await conn.fetch(f'SELECT 1 FROM posts p WHERE {1}')\n"
    tree = ast.parse(src)
    texts = [_literal(n) for n in ast.walk(tree) if _literal(n)]
    assert any(_READS_POSTS.search(t) for t in texts)
    # ...and the real tree has both filtered and reviewed readers.
    assert len(_unfiltered_reads()) >= 5
