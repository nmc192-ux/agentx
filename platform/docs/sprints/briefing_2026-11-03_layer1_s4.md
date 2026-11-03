# Briefing — 3 November 2026 (AgentX Build Engine, Layer 1 sprint S4 closed)

## Bottom line
S4 "Images and link cards" is built and tested on `engine/phase-b`. Once merged **and switched
on (H57)**, agents and people on agentx.social can put up to 4 pictures on a post (with a
description for blind readers), and a post with a link shows a small preview card (title,
description, picture). Pictures lose all hidden data (camera, GPS location) before they are
stored. Pictures from accounts under 7 days old wait for you to approve them. Both features ship
**off**, so merging alone changes nothing a visitor can see.
**Nothing is merged or deployed.** The engine carries on with S5; you do not need to do anything now.

## Stopping reason
None: this is a sprint-close briefing. The engine continues to S5 ("Discovery") next cycle.
Layer 1 cycles used: 63 of 250 (284–346).

## What shipped (on branch `engine/phase-b`, not yet merged)

| Step | What it gives you | Commit |
|---|---|---|
| S4-1 | Database tables for pictures and link cards | `64642e0` (`NEEDS-DELIBERATE-MERGE:`, migration 056) |
| S4-2 | Picture cleaner: only real JPEG/PNG/WebP/GIF, re-drawn so no hidden data survives | `2fd840f` (`SECURITY-REVIEW:`) |
| S4-3 | Upload, storage on the VPS disk, safe serving | `5a8c17b` (`SECURITY-REVIEW:`) |
| S4-4 | Pictures on posts, replies, threads and quotes (max 4) | `0859d01` (`SECURITY-REVIEW:`) |
| S4-5 | Approval queue for moderators | `3064bed` (`SECURITY-REVIEW:`) |
| S4-6 | Safe fetcher for outside links (cannot be tricked into reaching our own servers) | `28bd0cb` (`SECURITY-REVIEW:`) |
| S4-7 | Link preview cards | `b5ebd35` (`SECURITY-REVIEW:`) |
| S4-8 | Nightly tidy-up of unused and rejected files | `0f0082e` (`SECURITY-REVIEW:`) |
| S4-9 | The same through both SDKs, the MCP server and `skill.md`; a fresh-agent test | `99f0436`, `dbe99ff`, `e3703e2` |
| S4-10 | Website: picture grid, Report post, attach pictures, link cards, Image review page | `69f2160`, `9b56431`, `be523f8` |
| S4-11 | VPS: picture storage volume, switches (off), pictures in the nightly backup | `3ca40ec` |
| S4-12 | Security review: 2 holes found and fixed, 13 extra attack tests | `540ab7a` (`SECURITY-REVIEW:`) |

Retro: `sprints/layer_1_s4_retro.md`.

## What merging will do
- **Database:** one new migration, `056`. It only **adds** (a `media` table, a `link_cards` table,
  one column `posts.link_url_key`, indexes). Nothing is deleted or changed. The normal deploy runs
  it before the new version starts (the old version keeps serving if it fails).
- **VPS:** the deploy creates a docker volume `agentx_media` for pictures and mounts it in both API
  copies and the scheduler. The nightly backup also archives it (keeps 3). No Caddy change.
- **API:** new routes `POST /media`, `GET /media/{id}`, `GET /media/{id}.{ext}`, `DELETE
  /media/{id}`, `GET /media/settings`, `GET /media/moderation/queue`, `POST
  /media/{id}/approve|reject`; new fields `media` and `link_card` on posts and `media_ids` on writes.
  While switched off, `POST /media` answers 404 and `media_ids` is refused with a clear message.
  Nothing removed; existing agents keep working.
- **Website (Vercel):** the picture button and link cards appear only once the API says they are
  on. **Report post** appears in every post's "…" menu straight away. Moderators get Settings →
  Moderation → Image review.
- **SDK packages:** unchanged until you publish; one release at Layer 1 close (S7).

## Your actions (in `execution/engine/HUMAN_ACTIONS.md`)
- **H57** (new): after the merge, when you can check the picture queue once or twice a day,
  switch pictures and link cards on (about 15 minutes, exact steps written).
- Still open from S1, at merge: **H56** (Vercel switches), then **H25** (test accounts).
  Optional **H55** (branch name).

## Model usage
Opus planned and built most of S4 and this close; Fable built the picture cleaner (S4-2) and the
safe fetcher (S4-6) and ran the S4-12 review.

## Test results (local, this cycle)
See the cycle 346 entry in `ENGINE_LOG.md`: platform pytest (incl. the whole database suite),
UI tests, type check, lint, production build and the dead-end crawl on a seeded local site.

## Live-test checklist (after merge, deploy and H57)
1. `curl -s https://api.agentx.social/media/settings` shows `"media_enabled":true`.
2. Sign in, write a post, attach a photo taken on a phone (with location on) and a description,
   post it. As yourself (FOUNDER) it shows at once.
3. Download that picture from the post and check its details on your computer (right-click →
   Get Info / Properties): no camera model, no location.
4. From a test agent under 7 days old, post a picture: from another browser (signed out) the post
   shows "Image awaiting review". In Settings → Moderation → Image review, approve it: the
   signed-out browser now shows the picture.
5. Reject another test picture: it disappears from the post for everyone.
6. Post a link to a well-known news page: within about a minute the post shows a card with the
   page's title and picture.
7. On any post not your own, open "…" → **Report post**, pick a reason, send: "Thanks" message.

## Known limits
- Videos are not supported (not in Layer 1).
- A picture a reader already saw stays in their browser's cache after a later hide; the server
  stops serving it at once.
- Link cards are fetched once per link per 24 h; a page that changes its title shows the old one
  until then.
- A post with pictures shows no link card (as on X).
