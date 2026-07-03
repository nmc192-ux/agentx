# Sprint 9-sec — Wallet-drain security fix

**Sprint:** 9-sec (second in the chain: 9 → **9-sec** → 9-wellknown)
**Goal:** Close the unauthenticated wallet-drain vulnerability in the `agent_economy` router — the single most important fix in Phase A. The loop prepares and locally tests the fix, but this is **security code on a pipeline that auto-deploys to production the moment DrJ merges.** So every commit here is labeled `SECURITY-REVIEW:` and the briefing tells DrJ, in the strongest terms, to read every line with Claude alongside before merging.
**Branch:** `phase-a-autonomous` (continues from Sprint 9, no stop between).
**Constitutional anchor:** `magna_carta_v1.md` (Article 24, Principle 4 — honest accountability; and the economy primitive must be trustworthy).
**Runs under:** `autonomous_loop_v1.md`.

---

## Why this sprint is isolated

The Fable-5 audit found that an endpoint in the `agent_economy` router lets any caller move funds out of any agent's wallet with no authentication. On a live platform with real token balances, this is catastrophic — anyone could drain anyone.

It is a separate sprint, not bundled with the safe fixes, for one reason: **it must get DrJ's full, undivided attention at review.** Bundled among five routine fixes, a security diff competes for focus exactly when it needs all of it. Isolated, DrJ reviews nothing but this — with Claude reading it alongside him.

**The deploy reality that governs this sprint:** DrJ's pipeline auto-deploys to production on merge — there is no manual approval gate (confirmed from the deploy run for commit 185c846). So the branch review is the ONLY checkpoint between this fix and production. That raises the bar: the fix must be correct, and DrJ must understand it, before merge. A wrong auth fix can *reintroduce* the hole while looking like it closed it — which is worse than the known hole, because it hides.

---

## The overriding principle for this sprint

**A security fix that DrJ does not understand is not safe to merge, even if it works.** The loop's job here is not just to write a correct fix — it is to write a fix DrJ can *understand well enough to approve*. That means: minimal, focused, clearly explained, no cleverness, no unrelated changes riding along. The diff should be as small and readable as the problem allows.

---

## Steps

### Step 1 — Understand the vulnerability precisely (Fable 5 — this is the crux)

Read the `agent_economy` router and its service. Identify exactly:
- Which endpoint(s) allow moving funds.
- What authentication/authorization currently exists (the audit says none or insufficient).
- How the rest of the platform does auth — what pattern do *other* protected endpoints use (DID + JWT per the earlier notes)? The fix must match the platform's existing auth pattern, not invent a new one.
- What the correct authorization rule is: presumably only the agent that owns a wallet (or an explicitly authorized party) may move funds from it.

Write this up plainly in the briefing: here is the hole, here is how funds move, here is who *should* be allowed, here is the platform's existing auth pattern the fix will use.

### Step 2 — Write the minimal fix (Fable 5)

Add the authentication/authorization check so that only the wallet's owning agent (or explicitly authorized party) can move its funds. Constraints:
- **Match the existing auth pattern** used elsewhere in the platform. Do not invent a new mechanism.
- **Minimal and focused.** Change only what closes the hole. No refactoring, no cleanup, no unrelated improvements riding along — those make the security diff harder to review.
- **Fail closed.** If auth is missing or invalid, the request is rejected. Never fall through to allowing the operation.
- **No secrets in code.** Use the platform's existing secret/key handling.

### Step 3 — Test the fix locally, hard (Fable 5 for test design, Sonnet to run)

Prove the fix works, both directions:
- An unauthenticated attempt to drain a wallet is **rejected** (401/403, not 200).
- An attempt by a *different* agent to drain someone else's wallet is **rejected**.
- A legitimate, properly-authenticated transfer by the wallet's owner **succeeds**.
- Existing economy tests still pass.
- Add a test that specifically asserts the vulnerability is closed (an unauthorized drain attempt fails) so it can never silently regress.

### Step 4 — Do NOT re-enable agent_economy yet

Leave `agent_economy` in the disabled list in `router_config.py`. The router stays gated until DrJ has reviewed and merged the fix AND deliberately enabled it via the Fly.io env var. Enabling a just-patched security-critical economic router is a conscious DrJ action, done after review, not an autonomous one.

### Step 5 — Commit with SECURITY-REVIEW label, write the review guide, continue

Commit with a `SECURITY-REVIEW:` message. In the combined briefing, write a dedicated **"Wallet security fix — review guide"** section that walks DrJ through:
- The vulnerability in plain language (what could happen before the fix).
- Exactly what the fix changes, file by file, in terms a non-specialist can follow.
- What each test proves.
- The exact sequence DrJ should follow: review the diff (with Claude), merge only when understood, watch it auto-deploy, then run a verification confirming an unauthorized drain attempt now fails against production, THEN enable the router via Fly.io.

Then **continue directly to Sprint 9-wellknown** — do not stop.

---

## Acceptance criteria

- [ ] Vulnerability precisely understood and documented in plain language
- [ ] Minimal, focused fix matching the platform's existing auth pattern
- [ ] Fix fails closed (missing/invalid auth → rejected)
- [ ] Local tests prove: unauth drain rejected, cross-agent drain rejected, owner transfer succeeds
- [ ] A regression test asserts the hole stays closed
- [ ] Existing economy tests still pass
- [ ] agent_economy stays disabled in repo config (enable is DrJ's post-review action)
- [ ] Commit labeled SECURITY-REVIEW
- [ ] Briefing has a plain-language "review guide" for DrJ
- [ ] Continued to Sprint 9-wellknown without stopping

## The review-and-deploy sequence for DrJ (this goes in the briefing)

1. Review the security diff — with Claude reading it alongside you. Do not merge until you understand what it does and why.
2. Merge only when understood. (Remember: merge = auto-deploy to production, no gate.)
3. Watch it deploy.
4. Run a verification: confirm an unauthorized wallet-drain attempt against production now fails.
5. Only then enable `agent_economy` via the Fly.io env var — turning the now-secured router on.

This is the one fix in Phase A where "understand before merge" is not optional. Take the time.
