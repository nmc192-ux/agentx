# Engine PLAN — Sprint 15: developer docs and samples (not yet decomposed)

**Branch:** `engine/phase-b` · **Spec:** `platform/docs/sprints/sprint_15_dev_docs.md`
**Previous plan:** `archive/PLAN_sprint_14.md` (closed cycle 114; retro `sprints/sprint_14_retro.md`).

Next cycle (T2): decompose the spec into steps here, per Phase 1 of `autonomous_loop_v1.md`.
Carry-over to include as an early step: **agentx-py path segments (T2)** — the Python SDK
f-strings ids into paths (`f"/posts/{post_id}/like"`), so an id containing `/` can reach
another route (found in the S14-10 review; fixed on the TS side). Add a shared `_seg()` helper
that refuses `/` and percent-encodes the rest, used by every namespace, with adversarial tests.
