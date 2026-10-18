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

Nothing here touches the database.
"""
from __future__ import annotations

import re
from typing import Iterable

__all__ = ["CLAIM_PATTERNS", "claim_problems", "is_truthful", "numbers_in"]

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
# The heartbeat's de-duplication stamp, e.g. " (03 Oct 12:00 UTC)" at the end.
_STAMP = re.compile(r"\s*\(\d{2} [A-Z][a-z]{2} \d{2}:\d{2} UTC\)\s*$")


def numbers_in(text: str) -> set[str]:
    """Every run of digits in *text* ("1,204" and "3.5" count as one)."""
    return set(_DIGITS.findall(text or ""))


def claim_problems(
    text: str, facts: Iterable[str] = (), quoted: Iterable[str] = (),
) -> list[str]:
    """What is wrong with *text* as a founder's own words, or [] when nothing
    is. *facts* are the fact sentences read this tick (the only allowed
    source of numbers); *quoted* are strings the founder repeats from
    others (removed before checking)."""
    body = _STAMP.sub("", text or "")
    for q in sorted({q for q in quoted if q}, key=len, reverse=True):
        body = body.replace(q, " ")
    problems = [f"claim:{name}" for name, rx in CLAIM_PATTERNS if rx.search(body)]
    allowed: set[str] = set()
    for f in facts:
        allowed |= numbers_in(f)
    problems += [f"number:{n}" for n in sorted(numbers_in(body) - allowed)]
    return problems


def is_truthful(text: str, facts: Iterable[str] = (), quoted: Iterable[str] = ()) -> bool:
    return not claim_problems(text, facts, quoted)
