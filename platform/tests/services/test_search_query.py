"""Layer 1 S5-1: the search query grammar (pure, no DB)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.services import search_query as sq
from src.services.hashtags import MAX_TAG_LENGTH
from src.services.search_query import SearchQueryTooComplex, SearchQueryTooLong, parse


# ── Free text ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q", ["", None, "   ", "\t\n", '""', '"   "'])
def test_empty(q):
    got = parse(q)
    assert got.empty and got.text == "" and not got.has_operators
    assert not got.matches_nothing and got.notes == ()


def test_plain_text_is_kept_with_single_spaces():
    got = parse("  agents   that  trade ")
    assert got.text == "agents that trade"
    assert not got.has_operators and not got.empty


def test_quoted_phrase_stays_one_text_word_even_with_operators_inside():
    got = parse('"from:@atlas has:media" #ai')
    assert got.text == '"from:@atlas has:media"'
    assert got.from_handle is None and not got.has_media
    assert got.tags == ("ai",)


def test_unclosed_quote_runs_to_the_end_as_text():
    got = parse('hello "open phrase from:atlas')
    assert got.text == 'hello "open phrase from:atlas'
    assert got.from_handle is None


@pytest.mark.parametrize("q", [
    "a & b", "a | b", "!a", "(a)", "a:b", "it's", "back\\slash", "100%", "a_b",
    "%_%", "'; DROP TABLE posts; --", "a <-> b", "x:*", "$1", "a''b",
])
def test_sql_and_tsquery_metacharacters_are_just_text(q):
    got = parse(q)
    assert got.text == q
    assert not got.has_operators and not got.matches_nothing


@pytest.mark.parametrize("q", ["http://x.io", "to:@atlas", "lang:en", "-from:atlas",
                               "from", "since", ":media", "has"])
def test_unknown_or_bare_operator_words_are_text(q):
    got = parse(q)
    assert got.text == q and not got.has_operators and not got.matches_nothing


def test_control_characters_and_nul_become_spaces():
    got = parse("a\x00b\x07c\x7fd\x85e")
    assert got.text == "a b c d e"
    assert "\x00" not in got.text


# ── from: ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("word", ["from:@atlas", "from:atlas", "FROM:@Atlas", "From:ATLAS"])
def test_from_with_or_without_at_any_case(word):
    got = parse(word)
    assert got.from_handle == "atlas" and got.text == "" and not got.empty
    assert not got.matches_nothing


@pytest.mark.parametrize("value", ["@", "", "ab", "@x", "a-b", "атлас", "a" * 31, "@at;las",
                                   "@atlas'--"])
def test_from_with_an_invalid_handle_matches_nothing(value):
    got = parse(f"hello from:{value}")
    assert got.matches_nothing and got.from_handle is None
    assert got.text == "hello"
    assert any("not a valid handle" in n for n in got.notes)


def test_same_from_twice_is_fine_two_different_match_nothing():
    assert parse("from:atlas from:@ATLAS").from_handle == "atlas"
    got = parse("from:atlas from:nova")
    assert got.matches_nothing and got.from_handle == "atlas"
    assert any("one author" in n for n in got.notes)


# ── has: ─────────────────────────────────────────────────────────────────────

def test_has_media_and_link():
    got = parse("has:media HAS:Link cats")
    assert got.has_media and got.has_link and got.text == "cats"


def test_unknown_has_value_is_text_with_a_note():
    got = parse("has:video cats")
    assert not got.has_media and not got.has_link and not got.matches_nothing
    assert got.text == "has:video cats"
    assert any("has:video" in n for n in got.notes)


# ── since: / until: ──────────────────────────────────────────────────────────

def test_since_and_until_window():
    got = parse("since:2026-11-01 until:2026-11-03")
    assert got.since == date(2026, 11, 1) and got.until == date(2026, 11, 3)
    assert got.since_at == datetime(2026, 11, 1, tzinfo=timezone.utc)
    # until is inclusive: everything before the next day's midnight
    assert got.until_before == datetime(2026, 11, 4, tzinfo=timezone.utc)


def test_same_day_window_is_allowed():
    got = parse("since:2026-11-03 until:2026-11-03")
    assert not got.matches_nothing


def test_repeated_dates_keep_the_narrowest_window():
    got = parse("since:2026-01-01 since:2026-06-01 until:2026-12-31 until:2026-09-30")
    assert got.since == date(2026, 6, 1) and got.until == date(2026, 9, 30)


def test_since_after_until_matches_nothing():
    got = parse("since:2026-11-05 until:2026-11-01")
    assert got.matches_nothing
    assert any("after" in n for n in got.notes)


@pytest.mark.parametrize("value", ["2026-13-01", "2026-02-30", "26-11-01", "2026/11/01",
                                   "yesterday", "", "1999-12-31", "2101-01-01",
                                   "9999-12-31", "2026-1-1", "２０２６-11-01"])
def test_bad_dates_match_nothing_with_a_note(value):
    got = parse(f"since:{value}")
    assert got.matches_nothing and got.since is None
    assert any("not a date" in n for n in got.notes)


def test_last_allowed_year_does_not_overflow():
    got = parse(f"until:{sq.MAX_YEAR}-12-31")
    assert got.until_before == datetime(sq.MAX_YEAR + 1, 1, 1, tzinfo=timezone.utc)


def test_no_dates_no_bounds():
    got = parse("cats")
    assert got.since_at is None and got.until_before is None


# ── #tags ────────────────────────────────────────────────────────────────────

def test_tags_lowercased_distinct_in_order():
    got = parse("#AI #ml #ai #Snake_Case")
    assert got.tags == ("ai", "ml", "snake_case") and got.text == ""


def test_trailing_punctuation_after_a_tag_is_ignored():
    assert parse("#ai, #ml.").tags == ("ai", "ml")


@pytest.mark.parametrize("word", ["#", "#123", "##ai", "#café", "#a-b", "a#b",
                                  "#" + "x" * (MAX_TAG_LENGTH + 1)])
def test_not_a_tag_is_text(word):
    got = parse(word)
    assert got.tags == () and got.text == word


def test_longest_tag_is_a_tag():
    assert parse("#" + "x" * MAX_TAG_LENGTH).tags == ("x" * MAX_TAG_LENGTH,)


# ── Mixed and caps ───────────────────────────────────────────────────────────

def test_mixed_query():
    got = parse('from:@atlas "market maker" has:media since:2026-10-01 #defi rates')
    assert got.from_handle == "atlas" and got.has_media and got.tags == ("defi",)
    assert got.since == date(2026, 10, 1)
    assert got.text == '"market maker" rates'
    assert got.notes == () and not got.matches_nothing


def test_operators_only_is_not_empty():
    got = parse("from:@atlas has:media")
    assert not got.empty and got.text == ""


def test_query_at_the_length_cap_is_allowed_over_is_refused():
    assert parse("a" * sq.MAX_QUERY_LENGTH).text == "a" * sq.MAX_QUERY_LENGTH
    with pytest.raises(SearchQueryTooLong):
        parse("a" * (sq.MAX_QUERY_LENGTH + 1))


def test_length_counts_after_trimming():
    assert parse("  " + "a" * sq.MAX_QUERY_LENGTH + "  ").text


def test_operator_cap():
    ok = " ".join(f"#t{i}" for i in range(sq.MAX_OPERATORS))
    assert len(parse(ok).tags) == sq.MAX_OPERATORS
    with pytest.raises(SearchQueryTooComplex):
        parse(ok + " has:media")


def test_repeated_operators_count_towards_the_cap():
    with pytest.raises(SearchQueryTooComplex):
        parse(" ".join(["has:media"] * (sq.MAX_OPERATORS + 1)))


def test_errors_are_value_errors_with_plain_messages():
    with pytest.raises(ValueError, match="at most 200 characters"):
        parse("x" * 201)
