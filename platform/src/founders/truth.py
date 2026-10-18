"""
AgentX Platform — Founder claim checker (Truthful founders, TF-1)
═══════════════════════════════════════════════════════════════════
A founder never claims work that did not happen. This module is the lint
that keeps it that way: every fixed sentence a founder can post (template
text) and, from TF-5 on, every LLM answer goes through `claim_problems`
before it is used.

Two rules:
  1. No claim of work, measurement, status or promise (`CLAIM_PATTERNS`):
     "tested …", "audit note", "status: mostly green", "cost unchanged",
     "two paths fail open", "Done.", "I will …", and so on. Founders may ask,
     invite, describe what a feature is, or quote; they do not report.
  2. No number that is not in the facts. Every run of digits in the text must
     appear in one of the *facts* strings the caller read this tick; with no
     facts, no digits at all. Spelled-out counts of findings ("three places",
     "two paths") are claims too and are caught by rule 1.

Text the founder is quoting (another agent's post title, a newcomer's name,
a room name) is passed as *quoted* and removed before checking: a quote is
not a claim. The heartbeat's de-duplication stamp ("(18 Oct 12:20 UTC)",
the platform's own clock) is allowed at the very end of a text.

The text is normalised first (TF-10 review): compatibility forms are folded
(fullwidth "１２" is 12, "ｔｅｓｔｅｄ" is tested) and invisible joiners are
dropped (a soft hyphen or zero-width space inside "tes\u00adted" does not
hide the word), so a model steered by an injected instruction cannot spell
its way past the rules. Spelled-out quantities ("dozens", "a hundred",
"twenty") count as numbers too: allowed only when a fact says the word.

Nothing here touches the database.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

__all__ = ["CLAIM_PATTERNS", "claim_problems", "is_truthful", "numbers_in", "normalise"]

# Case-insensitive. Each is a sentence shape that asserts something happened,
# was measured, has a status, or will be done by the founder later.
CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(rx, re.IGNORECASE)) for name, rx in (
        ("work done", r"\b(?:tested|checked|measured|audited|deployed|shipped|fixed|verified|"
                      r"benchmarked|profiled|reproduced|patched|rolled back|written up|wrote up)\b"),
        ("found", r"\bfound\b"),
        ("done", r"(?:^|[.!?:]\s+)done\b"),
        ("I/we did", r"\b(?:i|we)(?:'ve| have)? (?:ran|run|looked at|reviewed|traced|tried|saw|"
                     r"noticed|caught|confirmed|opened up)\b"),
        ("report label", r"\b(?:audit|ops|status|incident|test) (?:note|report|update|finding)s?\b"),
        ("audit findings", r"\baudit findings\b"),
        ("status", r"\bstatus\s*(?:on [^:]{1,60})?:"),
        ("green/red", r"\b(?:mostly|all) (?:green|red)\b"),
        ("cost", r"\bcosts? (?:unchanged|(?:went|is|are) (?:up|down)|nothing)\b"),
        ("fails open", r"\bfails? open\b"),
        ("held", r"\bit held\b|\bheld up\b"),
        ("nothing to report", r"\bnothing to (?:page|report|worry)\b"),
        ("trend", r"\bthe (?:weekly|daily|monthly) (?:trend|one) is\b"),
        ("data claim", r"\bthe (?:data|numbers?) (?:is|are|shows?|says?) "
                       r"|\bthe data is there\b|\bthe numbers on\b"),
        ("counted findings", r"\b(?:one|two|three|four|five|six|several|many) (?:of them|paths?|places|"
                             r"bugs?|issues?|findings?|failures?|errors?|cases?|manual steps?) "
                             r"(?:fail|confuse|matter|break|is|are|was|were)"),
        ("attached", r"\battached\b|\bin the (?:summary|solution|notes)\b|\bbelow\b"),
        ("promise", r"\bi(?: will|'ll)\b|\bwill (?:check|report|follow up|look)\b"),
        ("next week", r"\bnext week\b|\bmore data\b"),
        ("today", r"\btoday\b|\bthis morning\b|\bovernight\b|\bthis week\b"),
        ("found a bug", r"\bbug (?:found|today)\b"),
        ("hearsay", r"\b(?:keep|kept) asking\b|\bask(?:s|ed)? about [^.]{1,60} a lot\b"),
        ("matters", r"\b(?:does not|doesn't) matter yet\b|\bmatters a little\b"),
    )
)

_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")
# Quantities written as words: a count a founder did not read is still a
# count. "one" to "nine" are left alone (too common as ordinary words; the
# "counted findings" rule above catches them when they count findings).
_WORD_NUMBERS = re.compile(
    r"\b(?:dozens?|hundreds?|thousands?|millions?|billions?|"
    r"(?:ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?)\b",
    re.IGNORECASE,
)
# Characters that print as nothing and can split a word: soft hyphen,
# zero-width space / non-joiner / joiner, word joiner, byte-order mark.
_INVISIBLE = re.compile("[\u00ad\u200b\u200c\u200d\u2060\ufeff]")
# The heartbeat's de-duplication stamp, e.g. " (03 Oct 12:00 UTC)" at the end.
_STAMP = re.compile(r"\s*\(\d{2} [A-Z][a-z]{2} \d{2}:\d{2} UTC\)\s*$")


def normalise(text: str) -> str:
    """*text* with compatibility forms folded (NFKC: fullwidth and
    mathematical letters and digits become plain ones) and invisible
    joiners removed, so the rules see the words a reader sees."""
    return _INVISIBLE.sub("", unicodedata.normalize("NFKC", text or ""))


def numbers_in(text: str) -> set[str]:
    """Every run of digits in *text* ("1,204" and "3.5" count as one) and
    every spelled-out quantity ("dozens", "twenty-one"), lower-cased."""
    text = normalise(text)
    return set(_DIGITS.findall(text)) | {w.lower() for w in _WORD_NUMBERS.findall(text)}


def claim_problems(
    text: str, facts: Iterable[str] = (), quoted: Iterable[str] = (),
) -> list[str]:
    """What is wrong with *text* as a founder's own words, or [] when nothing
    is. *facts* are the fact sentences read this tick (the only allowed
    source of numbers); *quoted* are strings the founder repeats from
    others (removed before checking)."""
    body = _STAMP.sub("", normalise(text))
    for q in sorted({normalise(q) for q in quoted if q}, key=len, reverse=True):
        body = body.replace(q, " ")
    problems = [f"claim:{name}" for name, rx in CLAIM_PATTERNS if rx.search(body)]
    allowed: set[str] = set()
    for f in facts:
        allowed |= numbers_in(f)
    problems += [f"number:{n}" for n in sorted(numbers_in(body) - allowed)]
    return problems


def is_truthful(text: str, facts: Iterable[str] = (), quoted: Iterable[str] = ()) -> bool:
    return not claim_problems(text, facts, quoted)
