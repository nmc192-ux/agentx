"""
Adversarial tests for the founder claim checker (TF-10 sprint-close review).

The checker (`src/founders/truth.py`) is the last line between a model that
was steered by an injected instruction and a founder's public post. Each
test here is a way such a text could try to slip past it:
  • digits that are not ASCII (fullwidth "４０", Arabic-Indic "٤٠") still
    count as numbers, and fullwidth letters still spell a banned word
  • invisible characters inside a word ("tes­ted") do not hide it
  • a quantity written as a word ("dozens", "a hundred", "twenty-one") is a
    number the founder did not read; a fact that says the word allows it
  • removing a quoted string can neither build nor split a word or a number
  • the de-duplication stamp is only exempt at the very end of the text
  • a quoted string is removed only when it appears verbatim: a fragment of
    it carrying a number is still checked
"""
from __future__ import annotations

import pytest

from src.founders.truth import claim_problems, is_truthful, normalise, numbers_in

FACTS = ["40 new agents joined in the last 7 days, 12 of them in the last 24 hours."]


# ── Numbers that are not ASCII digits ────────────────────────────────────────

def test_fullwidth_digits_are_numbers_and_match_the_facts():
    assert numbers_in("４０ agents") == {"40"}
    assert claim_problems("４０ new agents joined in the last ７ days.", FACTS) == []
    assert claim_problems("４１ new agents joined.", FACTS) == ["number:41"]


def test_digits_of_other_scripts_are_numbers_the_facts_do_not_hold():
    assert claim_problems("٤٠ agents joined.", FACTS)          # Arabic-Indic forty
    assert claim_problems("४० agents joined.", FACTS)          # Devanagari forty
    assert claim_problems("⑫ agents joined.", FACTS) == []     # NFKC: ⑫ → 12, which a fact holds
    assert claim_problems("⑬ agents joined.", FACTS) == ["number:13"]


def test_fullwidth_and_styled_letters_still_spell_the_banned_word():
    assert "claim:work done" in claim_problems("I ｔｅｓｔｅｄ the feed.")
    assert "claim:work done" in claim_problems("I 𝐭𝐞𝐬𝐭𝐞𝐝 the feed.")      # mathematical bold
    assert "claim:promise" in claim_problems("Ｉ ｗｉｌｌ report back.")


# ── Invisible characters inside a word ───────────────────────────────────────

@pytest.mark.parametrize("joiner", ["­", "​", "‌", "‍", "⁠", "﻿"])
def test_an_invisible_character_does_not_hide_a_banned_word(joiner):
    assert "claim:work done" in claim_problems(f"I tes{joiner}ted the feed.")
    assert "claim:promise" in claim_problems(f"I wi{joiner}ll look into it.")
    assert claim_problems(f"4{joiner}1 agents joined.", FACTS) == ["number:41"]


def test_normalise_keeps_ordinary_text_as_it_is():
    plain = "40 new agents joined in the last 7 days. What would you add?"
    assert normalise(plain) == plain
    assert normalise("Founders' room: “the feed” — ok") == "Founders' room: “the feed” — ok"


# ── Quantities written as words ──────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Dozens of agents joined this week's rooms.",
    "A hundred new posts went up.",
    "Thousands of replies.",
    "Twenty-one agents joined.",
    "twenty one agents joined.",
    "Twelve agents joined.",
    "Ninety agents joined.",
    "Half a million posts.",
])
def test_a_spelled_out_quantity_is_a_number_the_founder_did_not_read(text):
    problems = claim_problems(text, FACTS)
    assert any(p.startswith("number:") for p in problems), (text, problems)


def test_a_fact_that_spells_the_word_allows_it():
    assert claim_problems("A dozen agents joined.", ["A dozen agents joined this week."]) == []
    assert claim_problems("A dozen agents joined.", FACTS) == ["number:dozen"]


@pytest.mark.parametrize("text", [
    "One change worth knowing about: replies now nest.",     # the ATLAS opener
    "Two paths are open to you here.",                         # small counts stay ordinary words
    "Often the first step is the hardest.",                    # "ten" inside a word
    "The tenth reply is as welcome as the first.",
    "Forty-four is a street, not a count, but the word is still a count.",
])
def test_small_counts_and_words_containing_number_words_are_fine(text):
    problems = [p for p in claim_problems(text, FACTS) if p.startswith("number:")]
    if text.startswith("Forty-four"):
        assert problems == ["number:forty-four"]
    else:
        assert problems == [], (text, problems)


# ── Quoted strings cannot build or split anything ────────────────────────────

def test_removing_a_quote_cannot_build_a_word_or_a_number():
    # "tes" + quote + "ted" must not become "tested"; "4" + quote + "0" must not become 40.
    assert "claim:work done" not in claim_problems("tesATLASted", quoted=("ATLAS",))
    assert claim_problems("4ATLAS0 agents joined.", FACTS, quoted=("ATLAS",)) == [
        "number:0", "number:4"]


def test_a_fragment_of_a_quoted_string_is_still_checked():
    title = "Verified: 7 wallets drained by the founders"
    # The whole title is a quote; a piece of it with the number is the founder's own words.
    assert claim_problems(f"On “{title}”: what do you mean?", quoted=(title,)) == []
    assert claim_problems("Yes, 7 wallets drained — what next?", quoted=(title,)) == ["number:7"]
    assert "claim:work done" in claim_problems("Verified. What next?", quoted=(title,))


def test_quotes_are_matched_after_normalisation():
    assert claim_problems("Hello Ｓｃｏｕｔ-４２!", quoted=("Scout-42",)) == []


# ── The stamp ────────────────────────────────────────────────────────────────

def test_the_stamp_is_exempt_only_at_the_very_end():
    assert claim_problems("40 new agents joined. (18 Oct 12:20 UTC)", FACTS) == []
    assert claim_problems("(18 Oct 12:20 UTC) 40 new agents joined.", FACTS) != []
    assert claim_problems("40 joined (99 Oct 00:00 UTC) and more.", FACTS) != []
    assert "claim:work done" in claim_problems("Tested. (18 Oct 12:20 UTC)")


def test_is_truthful_agrees_with_claim_problems():
    assert is_truthful("40 new agents joined in the last 7 days.", FACTS)
    assert not is_truthful("Dozens joined.", FACTS)
