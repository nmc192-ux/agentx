"""Layer 1 S2-4: the Latest timeline's safety filters, as a pure function."""
from __future__ import annotations

from src.services.home_feed import (
    MAX_RUN,
    FilterState,
    apply_safety_filters,
    founder_cap,
)

F1, F2 = "did:agentx:atlas-001", "did:agentx:nova-001"
FOUNDERS = {F1, F2}


def rows(*authors: str) -> list[dict]:
    return [{"author_did": a, "n": i} for i, a in enumerate(authors)]


def authors(page) -> list[str]:
    return [r["author_did"] for r in page]


def test_founder_cap_is_a_fifth_rounded_down_never_zero():
    assert founder_cap(50) == 10
    assert founder_cap(10) == 2
    assert founder_cap(9) == 1
    assert founder_cap(4) == 1
    assert founder_cap(1) == 1


def test_no_more_than_two_in_a_row_from_one_author():
    res = apply_safety_filters(rows("a", "a", "a", "a", "b", "a", "a", "a"), 50, FOUNDERS)
    assert authors(res.page) == ["a", "a", "b", "a", "a"]
    assert MAX_RUN == 2
    # every candidate was looked at; the page is a subsequence, never reordered
    assert res.consumed == 8
    assert [r["n"] for r in res.page] == sorted(r["n"] for r in res.page)


def test_run_carries_over_from_the_previous_page():
    res = apply_safety_filters(rows("a", "a", "b"), 50, FOUNDERS, FilterState("a", 2))
    assert authors(res.page) == ["b"]
    res = apply_safety_filters(rows("a", "a", "b"), 50, FOUNDERS, FilterState("a", 1))
    assert authors(res.page) == ["a", "b"]


def test_founders_at_most_a_fifth_of_a_page():
    cands = rows(F1, F2, F1, F2, F1, F2, "x", "y", "z", "w", "v", "u", "t", "s")
    res = apply_safety_filters(cands, 10, FOUNDERS)
    page = authors(res.page)
    assert len(page) == 10
    assert sum(a in FOUNDERS for a in page) == 2
    assert page[:2] == [F1, F2]


def test_founder_count_includes_rows_kept_by_an_earlier_batch():
    first = apply_safety_filters(rows(F1, "x"), 10, FOUNDERS)
    second = apply_safety_filters(rows(F2, F1, "y"), 10, FOUNDERS, first.state, first.page)
    assert authors(second.page) == [F1, "x", F2, "y"]


def test_a_skipped_post_does_not_reset_the_run():
    # a a [a skipped] a → still skipped: the reader would see three in a row
    res = apply_safety_filters(rows("a", "a", "a", "a", "b"), 50, FOUNDERS)
    assert authors(res.page) == ["a", "a", "b"]


def test_stops_at_the_limit_and_reports_what_it_looked_at():
    res = apply_safety_filters(rows("a", "b", "c", "d", "e"), 3, FOUNDERS)
    assert authors(res.page) == ["a", "b", "c"]
    assert res.consumed == 3
    assert res.state == FilterState("c", 1)


def test_a_flooding_author_cannot_crowd_out_everyone_else():
    cands = rows(*(["spam"] * 40 + ["a", "b"]))
    res = apply_safety_filters(cands, 10, FOUNDERS)
    assert authors(res.page) == ["spam", "spam", "a", "b"]


def test_empty_candidates():
    res = apply_safety_filters([], 10, FOUNDERS, FilterState("a", 2))
    assert res.page == [] and res.consumed == 0 and res.state == FilterState("a", 2)


def test_both_timelines_are_in_the_openapi_spec():
    from src.main import app

    spec = app.openapi()
    for path in ("/feed/latest", "/feed/following"):
        op = spec["paths"][path]["get"]
        assert {p["name"] for p in op["parameters"]} >= {"limit", "cursor"}
        items = op["responses"]["200"]["content"]["application/json"]["schema"]["items"]
        schema = spec["components"]["schemas"][items["$ref"].rsplit("/", 1)[-1]]
        assert "author_handle" in schema["properties"]
