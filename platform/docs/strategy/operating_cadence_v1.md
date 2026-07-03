# AgentX Operating Cadence v1

**Document type:** Operating rhythm
**Version:** v1
**Owner:** DrJ (Jahanzeb Hussain)
**Issued:** 5 May 2026
**Status:** Active
**Constitutional anchor:** `magna_carta_v1.md`
**Operational anchor:** `strategic_plan_v2.md`

---

## Preamble

The magna carta says what AgentX is. The strategic plan says what gets built and in what order. This document says *how the founder actually works on AgentX day to day.* It is the smallest of the three documents deliberately — an operating cadence that becomes a burden defeats itself.

Six commitments this document keeps:

1. Every loop has a defined trigger and a defined output.
2. Every loop can be safely skipped when the district, family, or another project demands it. Skip-safety is a feature, not a failure.
3. The daily loop is 30 minutes or less. If it grows past that, this document gets amended.
4. State survives between sessions. `state_of_agentx.md` is the single fastest way to reload context — for the founder, for a future collaborator, for a future strategic session.
5. Decision friction stays low. Reversible decisions never wait on a formal review. Irreversible decisions get named as such and pause briefly for a yes/no.
6. Nothing here contradicts the magna carta. If it does, the magna carta wins.

Five nested loops, from fastest to slowest. Each has a trigger, a duration, a set of artifacts produced, and an honest skip-rule.

---

## Loop 1 — The daily loop (30 min, weekdays)

**Trigger:** Morning coffee, or first available 30-minute window.

**What happens:** Open `state_of_agentx.md`. Read yesterday's "what's next" line. Do one of three things:

- If Claude Code is mid-sprint, spend the window running the next command, reviewing output, or answering a blocking question Claude Code raised.
- If a sprint is between steps and awaiting your review, do the review, merge or request changes, update `state_of_agentx.md`.
- If nothing is in flight, spend the window either: reading one section of the audit/plan/magna carta with fresh eyes, or writing tomorrow's "what's next" line yourself.

**Artifact produced:** One updated line at the top of `state_of_agentx.md` — "As of [date], AgentX is at [X]. Next action: [Y]." Nothing more.

**Skip-rule:** Any day with a district emergency, family need, or Scoopfeeds/Synapse push. No make-up sessions. Skipped days accumulate but do not compound guilt.

**Failure mode:** If the daily loop skips for more than 5 consecutive weekdays, that is a signal — either the loop is too heavy or life has genuinely intervened. Trigger the weekly loop early to reassess.

---

## Loop 2 — The weekly loop (2 hours, one weekend session)

**Trigger:** Weekend, any day, whenever the calendar permits.

**What happens:** Three things, in order:

1. *Update `state_of_agentx.md` fully.* Not just the top line — the full state: what shipped this week, what got blocked, what changed strategically, what the founding agents did (once they're live), what the audit numbers now say. Ten minutes.

2. *Read the last week's Claude Code outputs and commits.* Look at what actually happened, not what you thought would happen. Notice discrepancies. Twenty minutes.

3. *Plan the next week.* One paragraph in `state_of_agentx.md` describing what the coming week is aimed at. If a sprint is mid-flight, this is easy — plan the next 2–3 steps. If a sprint is done and the next isn't yet drafted, decide whether the next week is drafting the next sprint prompt (which usually requires a strategic session with Claude) or executing existing work. Ten minutes.

The remaining 60–80 minutes are actual work: reviewing code, drafting a sprint prompt yourself if it's simple enough, reading the audit, updating a doc, or (once the platform is live) checking on the founding agents' activity.

**Artifact produced:** Updated `state_of_agentx.md`, potentially a commit or two, potentially a new sprint prompt drafted.

**Skip-rule:** Any weekend where the district or family need is greater. Skipped weekends do not accumulate; the next weekend is fresh.

**Failure mode:** If the weekly loop skips for 3 consecutive weekends, trigger a strategic session — something has shifted structurally in your available time and the plan needs to acknowledge it.

---

## Loop 3 — The sprint loop (variable, per sprint)

**Trigger:** Existence of a written sprint prompt (`sprint_N_<name>.md`).

**What happens:** The sprint executes over a variable number of daily and weekly loops. When the sprint is done, four artifacts must exist before the sprint counts as closed:

1. *Code merged and deployed* to the relevant environment.
2. *Acceptance criteria verified against the live deployment* — each check-off in the sprint prompt confirmed by an actual `curl`, `pytest`, or UI check, not by intent.
3. *Sprint retro* written to `docs/sprints/sprint_N_retro.md`. Five to eight paragraphs. Structure below.
4. *`state_of_agentx.md` updated* to reflect the new post-sprint reality.

Only when all four exist does the sprint close. This is the (d) answer from your loop-closure question — non-negotiable.

**Sprint retro template:**

```markdown
# Sprint N — <name> — Retro

**Sprint:** N
**Dates:** <start> → <end>
**Merged in:** <commit hash(es)>

## What was intended
One paragraph. The sprint's stated goal.

## What actually shipped
One paragraph. What is now in production that wasn't before.

## What we learned
One paragraph on facts about the codebase, the platform, or the environment
that we didn't know before this sprint. This is the compounding knowledge.

## What we deferred
One paragraph. What was in scope but got dropped, and why. Feeds into the
open items for the next sprint.

## What changed strategically
One paragraph. Any implication for the strategic plan or the magna carta.
If any, name the article/section that may need amending.

## Next
One paragraph. The next sprint's working title, or the next question that
must be answered before the next sprint can be drafted.
```

**Skip-rule:** Sprints do not skip. They pause. A paused sprint is still the current sprint; a paused sprint does not get bypassed for a new one. This constraint keeps the sequence honest.

**Failure mode:** If a sprint is paused for more than 4 weeks, treat that as a strategic signal — trigger a strategic session to decide whether the sprint scope is wrong, the sequence is wrong, or the founder's availability has shifted.

---

## Loop 4 — The phase loop (per Phase A → E)

**Trigger:** Sprint retros suggest a phase's exit criteria are close to being met (or clearly are not being met).

**What happens:** A phase boundary is a real moment. Three things:

1. *Verify every phase exit criterion.* Not just intent — the actual audit-style verification. `curl`, `psql`, `pytest`, whatever it takes. Anything unverified stays as an unmet criterion.

2. *Strategic session.* We (this Claude session, or whichever future strategic partner) sit down and draft the next phase's kickoff brief. This includes: current-state summary (drawn from the latest audit and the sprint retros), sprint sequence for the phase, phase exit criteria, phase-specific risks.

3. *Amend the plan if reality diverges.* If Phase A revealed that a Phase B assumption is wrong, the plan gets amended into v2.1, v2.2, or (if the divergence is structural) v3. This is normal.

**Artifact produced:** Phase kickoff brief in `docs/phases/phase_<X>_kickoff.md`, plan amendment if warranted.

**Skip-rule:** Phase boundaries do not skip. They are the moments the project's shape gets checked against reality.

**Failure mode:** If two consecutive phase boundaries produce major amendments to the plan, the strategic assumptions are wrong at a deeper level — trigger a magna carta review.

---

## Loop 5 — The quarterly loop (once every three months)

**Trigger:** End of each calendar quarter, or three months since the last quarterly review, whichever comes first.

**What happens:** The magna carta's Article 5 commits to a quarterly competitive landscape scan. Article 21 lists open questions that should be revisited quarterly. This loop is the moment for both.

Three artifacts:

1. *`competitive_landscape_<yyyy>q<n>.md`* — an honest scan of what OpenAI, Anthropic, Google, Meta, LangChain, CrewAI, and any well-funded startup has shipped, announced, or committed to in the agent-infrastructure space in the last quarter. This is where the founder's stated fear — "a big tech player builds this at advanced state" — gets checked against reality every three months.

2. *Open items status update.* Each item in Magna Carta Appendix A and Plan v2 §11 gets a one-line status: still deferred, in progress, resolved, obsolete.

3. *One paragraph honest assessment* of whether the plan is working. Are we compounding? Are we stuck? Is the theory of change producing what it predicted? This paragraph appears at the top of `state_of_agentx.md` for the next quarter.

**Skip-rule:** Quarterly reviews do not skip. They are the project's honesty mechanism. If a quarter passes with no review, the loop failed and a review is overdue.

**Failure mode:** If the quarterly review reveals that a magna carta principle is being violated in practice — even if by accident — that is a five-alarm signal. Stop and re-align before the next sprint.

---

## Interaction with strategic sessions (Claude)

Strategic sessions happen at two triggers per Plan v2 §5 and your loop question:

- **Phase boundaries** — every A→B, B→C, C→D transition is a strategic session.
- **Reality surprises** — an audit finding, a competitor move, a tech shift that changes the assumptions.

Strategic sessions are not scheduled. They are triggered by state, not by calendar. The daily and weekly loops keep AgentX moving in between; strategic sessions are the moments the direction gets checked.

**Preparation for a strategic session:** the current `state_of_agentx.md` plus the most recent sprint retro plus (if applicable) the latest audit. That's the entire context load. Everything else lives in the committed docs and can be pulled as needed.

---

## Decision-making inside the loop

Restating from Plan v2 §5 with the interaction pattern that matches your (c)+(d) answer:

- *Reversible decisions* (which library, which folder name, which retro format): Claude Code decides, moves on, notes it in the retro if interesting.
- *Tactical decisions* (which sub-task to tackle next, which of two roughly-equivalent approaches): you decide, in the daily or weekly loop, with a one-line answer if that's all the decision needs.
- *Strategic decisions* (whether to enter augmented mode, whether to accept a partnership offer, whether to amend the magna carta): strategic session with Claude. Formal, but not lengthy — usually resolvable in one session.

Decision friction rule: if a decision is taking more than one back-and-forth to resolve, it's probably strategic. Kick it to a strategic session rather than resolving it under pressure.

---

## What "finalized" means, precisely

Your (d) answer: *the strategic documents are complete enough that if you got hit by a bus tomorrow, someone else could pick up AgentX and know exactly what to do.*

This is a documentation-completeness target. Concretely it means:

- A reader who has never seen AgentX can read `docs/strategy/README.md` → magna carta → Plan v2 → `state_of_agentx.md` → latest sprint retro, in that order, and by the end know:
  - What AgentX is and why it exists
  - What is currently shipped and what isn't
  - What the next sprint is and how to execute it
  - What the strategic bet is and what would break it
  - Where to find every open thread and what depends on what

By this definition, AgentX becomes "finalized-enough" when:

1. `state_of_agentx.md` exists and is being kept current (weekly)
2. Every sprint has a retro
3. Every phase has a kickoff brief
4. Quarterly reviews are on record
5. The magna carta and plan have both been amended at least once each from real experience (proving the amendments process works, not just that it exists)

By this definition, finalization is achievable in 90 days if the loop is executed with discipline. It doesn't require Phase A to be complete — it requires the *rhythm* to be complete.

---

## The 90-day finalization commitment

Concretely, over the next 90 days:

- **Days 1–7:** Create `state_of_agentx.md`. Start updating daily. Sprint 9 kicks off.
- **Days 8–21:** Sprint 9 executes. Daily loop practiced. Weekly loop practiced.
- **Days 22–28:** Sprint 9 closes with retro. First retro is on record. `state_of_agentx.md` reflects post-Sprint-9 reality.
- **Days 29–56:** Sprints 10 and 11. Two more retros. Daily and weekly loops running.
- **Days 57–70:** Sprint 12. Third retro. Phase A boundary check. Phase A → B strategic session. First phase kickoff brief produced.
- **Days 71–90:** Sprint 13 (first Phase B sprint). First quarterly review conducted. First `competitive_landscape_2026q3.md` produced. Magna carta and plan amended based on 90 days of real experience.

At day 90, every artifact from the "finalized-enough" list exists at least once. The project is now demonstrably self-carrying. The founder can be absent for two weeks and the loop resumes without a strategic session on return.

---

## What could break this loop

Honest failure modes worth naming.

**The daily loop feels like homework.** If it does, this document is wrong and needs to be amended. The daily loop should feel like *checking on something you care about*, not *completing an obligation*. If it consistently feels like the latter, drop the daily loop back to (d) opportunistic and rely on the weekly loop instead.

**Claude Code produces work faster than you can review.** This is a real risk given your review-before-merge posture. Mitigation: allow yourself to batch reviews on the weekly loop rather than daily. Don't let review debt block sprint progress; either delegate more to Claude Code's judgment on reversibles, or accept that sprints take longer than they otherwise would.

**Strategic sessions get triggered too often.** If reality surprises AgentX every week, that's not a well-founded strategic plan. Aim for one strategic session per phase boundary plus one per genuine surprise. More than one per month is a signal.

**The retros become perfunctory.** The moment a retro is written to satisfy the process rather than to capture what actually happened, it stops compounding knowledge. If you catch yourself writing a retro cynically, name it in the retro itself — that itself is the honest observation.

**Sprint 9 reveals the platform is more broken than expected.** Possible. If so, Sprint 9 becomes 9a and 9b, the phase timeline extends, and Plan v2.1 amendment captures it. This is not failure; this is the loop doing its job.

---

## Amendments

This document is binding until amended. The amendments process mirrors Magna Carta Article 23. A cadence that stops fitting the founder's life is a cadence that needs updating, not a founder who is failing.

---

# Changelog

- **v1 (5 May 2026):** Initial operating cadence. Five nested loops, 90-day finalization commitment, honest skip-safety on the daily and weekly loops.
