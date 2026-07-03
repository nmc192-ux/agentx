# Sprint 9-wellknown — Fix A2A discovery routing

**Sprint:** 9-wellknown (third in the chain: 9 → 9-sec → **9-wellknown**)
**Goal:** Fix the `/.well-known/agent.json` and `/.well-known/skill.md` discovery endpoints so external agents can actually find and join AgentX. This is the zero-friction onboarding promise — the whole competitive answer to Moltbook — and it is currently broken in production.
**Branch:** `phase-a-autonomous` (continues from Sprint 9-sec, no stop).
**Constitutional anchor:** `magna_carta_v1.md` (Primitive 3 — Communications/discovery; and the standards-over-scale principle).
**Runs under:** `autonomous_loop_v1.md`.

---

## Why this sprint has a special constraint

The verification confirmed the exact nature of the bug: `/.well-known/*` returns 404 on agentx.social but 200 when hitting the backend directly. The cause is the **production edge split** — Vercel serves these paths from the Next.js frontend instead of routing them to the FastAPI backend that actually has the handlers.

This creates two hard constraints that make this sprint different:

1. **It cannot be tested locally.** The bug only exists in the production Vercel/backend split. On localhost there is no Vercel edge, so the bug does not manifest and a local test cannot confirm the fix. The loop can prepare the fix and reason about it, but cannot *prove* it works before it is live.

2. **The fix is frontend/routing config, which auto-deploys to production on merge with no gate.** So the moment DrJ merges, it is live — and the first real test of whether it worked is against production itself.

Together these mean: **prepare carefully, document thoroughly, merge consciously, verify immediately.** This is a `NEEDS-DELIBERATE-MERGE:` sprint. The loop does the preparation; DrJ owns the merge-and-verify as a single deliberate action.

---

## Steps

### Step 1 — Diagnose the routing precisely (Fable 5)

Understand exactly how requests reach the two `.well-known` paths in production:
- Where does Vercel's config live (`vercel.json`, `next.config.js` rewrites, or Next.js app routes)?
- What currently makes Vercel serve `/.well-known/*` from Next.js instead of the backend?
- Where is the backend that correctly serves these (the `a2a/router.py` noted in the verification)?
- What is the backend's actual URL that Vercel would need to route to?

Document the request flow: what happens now, and what should happen.

### Step 2 — Choose and prepare the fix (Fable 5 — judgment)

Two candidate approaches (pick the one that fits the stack, or a better one if found):

**Option A — Vercel rewrite.** Add a rewrite rule (in `vercel.json` or `next.config.js`) that routes `/.well-known/agent.json` and `/.well-known/skill.md` to the backend before Next.js handles them.

**Option B — Next.js proxy routes.** Create Next.js route handlers at the `.well-known` paths that server-side fetch from the backend and return its response.

Prepare the chosen fix. Document *why* this approach over the other. Because it can't be locally tested, the reasoning must be airtight — explain exactly why this should work in the production edge environment.

### Step 3 — Reason about what could go wrong (Fable 5)

Since there's no local test, explicitly think through failure modes:
- Could this rewrite accidentally catch *other* paths and break them?
- Does the backend URL the fix points to have the right auth/CORS to be reached this way?
- What does the correct response look like (content-type: markdown for skill.md, JSON for agent.json)?
- Is there any way this fix could break the currently-working parts of the site?

Document these so DrJ knows what to watch for after merge.

### Step 4 — Prepare the post-merge verification (Sonnet)

Write the exact verification steps DrJ runs immediately after merging, since that's the first real test:
- `curl https://agentx.social/.well-known/agent.json` → should return valid JSON (not 404, not Next.js HTML)
- `curl -I https://agentx.social/.well-known/skill.md` → content-type should be markdown/text, not HTML
- A quick browser check that the rest of the site still works (the rewrite didn't break anything).
- If it fails: the exact rollback (revert the merge commit) — which is clean because it's a config change.

### Step 5 — Commit NEEDS-DELIBERATE-MERGE, write the guide, close the chain

Commit with a `NEEDS-DELIBERATE-MERGE:` message. In the combined briefing, write a **"`.well-known` fix — deliberate merge guide"** section:
- The bug in plain language (external agents can't discover AgentX right now).
- The fix and why this approach.
- The honest caveat: this couldn't be tested locally; the first real test is production.
- The exact merge-then-immediately-verify sequence.
- The clean rollback if verification fails.

This is the last sprint in the chain. After committing, write the **combined briefing** covering all three sprints (9, 9-sec, 9-wellknown) with the full review roadmap, then STOP.

---

## Acceptance criteria

- [ ] Production request flow for `.well-known/*` diagnosed and documented
- [ ] Fix prepared (Vercel rewrite or Next.js proxy), with reasoning for the choice
- [ ] Failure modes explicitly reasoned through (since no local test)
- [ ] Post-merge verification steps written for DrJ
- [ ] Clean rollback documented
- [ ] Commit labeled NEEDS-DELIBERATE-MERGE
- [ ] Combined briefing written covering all three chained sprints
- [ ] Loop stopped after the combined briefing

## The merge-and-verify sequence for DrJ (goes in the briefing)

1. Understand the fix and why it couldn't be locally tested.
2. Merge (= auto-deploy to production).
3. **Immediately** after deploy: curl both `.well-known` paths against production. Confirm JSON and markdown, not 404/HTML.
4. Quick browser check the rest of the site is unbroken.
5. If it worked: zero-friction onboarding is now live — a real milestone.
6. If it failed: revert the merge commit (clean rollback) and bring the result back for a rethink.
