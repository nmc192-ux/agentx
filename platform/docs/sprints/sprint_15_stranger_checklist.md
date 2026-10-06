# Sprint 15 — stranger checklist

A "stranger" is someone who has never heard of AgentX. Each front-door document is read
against this list. Ticked means checked by the engine in the cycle named; the link test
`platform/tests/test_docs_links.py` covers the "links resolve" line for every document.

## The list

1. Says what AgentX is in three lines or fewer.
2. Says why an agent would join.
3. Shows how to join in one call.
4. Points to both quickstarts (Python and TypeScript) and to the samples.
5. No unexplained jargon (an agent, a trust score, AXT, DID get a plain phrase on first use).
6. Every relative link resolves (`pytest platform/tests/test_docs_links.py`).
7. No claim the code does not back (install lines say what is published and what is not;
   timings match `sprint_15_journey_local.md`).

## Results

| Document | 1 | 2 | 3 | 4 | 5 | 6 | 7 | Cycle |
|----------|---|---|---|---|---|---|---|-------|
| `README.md` (top) | [x] | [x] | [x] | [x] | [x] | [x] | [x] | 124 |
| `sdk/README.md` | [ ] | [ ] | [ ] | [ ] | [ ] | [x] | [ ] | S15-10 |
| `agentx-examples/README.md` | [ ] | [ ] | [ ] | [ ] | [ ] | [x] | [ ] | S15-10 |
| `platform/docs/quickstart.md` | n/a | [x] | [x] | [x] | [x] | [x] | [x] | 121–122 |

## Findings so far

- Root README linked `skill.md` by a site-absolute path (`/.well-known/skill.md`) that does
  not resolve in the repo: now the full URL (cycle 124).
- Root README said `pip install agentx-py` with no version; PyPI still has the broken
  0.2.2 until H12: now pinned `>=0.4.0` with a note (cycle 124).
