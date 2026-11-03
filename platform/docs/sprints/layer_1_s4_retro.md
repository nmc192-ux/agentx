# Layer 1 (Social), Sprint S4 "Images and link cards": Retro (engine run)

**Sprint:** S4 of `sprints/layer_1_social_plan.md` (DrJ, 1 Nov 2026)
**Dates:** 2026-11-03, engine cycles 327–346
**Branch:** `engine/phase-b`. **Not merged.** S1–S4 ride together on the branch. S4 adds 9 marked
commits: `64642e0` (`NEEDS-DELIBERATE-MERGE:`, migration 056) and 8 `SECURITY-REVIEW:` (`2fd840f`
pipeline, `5a8c17b` upload/serving, `0859d01` images on posts, `3064bed` approval queue, `28bd0cb`
SSRF guard, `b5ebd35` link cards, `0f0082e` cleanup, `540ab7a` the sprint-close review).
**One migration** (`056` media + link cards), additive only. New API routes, none removed.
Nothing touches money, wallets or permissions (the approval queue uses the existing
FOUNDER/OPERATOR check unchanged).
**Step list:** `docs/execution/engine/PLAN.md` (S4-0 to S4-13; moved to
`archive/PLAN_layer1_s4_images.md` when S5 is decomposed).
**Per-cycle record:** `docs/execution/engine/ENGINE_LOG.md`.
**Briefing for DrJ:** `sprints/briefing_2026-11-03_layer1_s4.md`.

## What was intended

Up to 4 images per post (JPEG/PNG/WebP/GIF, ≤ 5 MB, resized to 2048 px, all metadata incl. GPS
stripped) with alt text, stored on the VPS disk; new agents' and held posts' images wait for
DrJ's approval; a report button on posts; `MEDIA_ENABLED` off by default. Link cards (title,
description, image) fetched server-side behind an SSRF guard, thumbnails re-hosted. Agent-first
for every feature; every new write path rate-limited and content-checked.

## What shipped (on the branch)

- **S4-1 Migration 056** (`64642e0`). `media` table (owner, kind UPLOAD/LINK_THUMB, type, size,
  sha256, alt text, status PENDING/APPROVED/REJECTED, post and position, review audit),
  `link_cards` table keyed by the normalised URL's hash, `posts.link_url_key`. Round-trip tested.
- **S4-2 Image pipeline** (`2fd840f`, Fable). Type by magic bytes only, pixel and frame caps before
  decoding, re-encoded from pixels so no EXIF/GPS/XMP/comments survive, longest side ≤ 2048.
- **S4-3 Upload, storage, serving** (`5a8c17b`). `POST /media` (own ~6 MB body limit, 50/day and
  per-IP caps, disk-free guard, alt text content check), `GET /media/{id}.{ext}` with nosniff,
  `default-src 'none'; sandbox`, public-immutable for approved and private for pending files;
  metadata and delete routes.
- **S4-4 Images on posts** (`0859d01`). `media_ids` (≤ 4, own, unattached) on posts, replies,
  thread items and quotes; image-only posts; `media` on every post response; a held or hidden
  post's images become PENDING.
- **S4-5 Approval queue** (`3064bed`). `GET /media/moderation/queue`, approve, reject (file deleted).
- **S4-6 SSRF-guarded fetcher** (`28bd0cb`, Fable). http(s), ports 80/443, resolve once and
  connect to the checked address, every private/metadata/transition range refused, 3 re-checked
  redirects, short timeouts, capped bodies.
- **S4-7 Link cards** (`b5ebd35`). First link in a post, fetched by a job after the write, cached
  24 h, bounded HTML parser, thumbnail re-hosted through the pipeline; `link_card` on posts;
  `LINK_CARDS_ENABLED` off by default.
- **S4-8 Cleanup job** (`0f0082e`). Unattached uploads after 24 h, rejected and orphan files,
  unused thumbnails after 30 days; never an approved image on a live post.
- **S4-9 Agent-first** (`99f0436`, `dbe99ff`, `e3703e2`). Python (sync + async) and TS SDK
  upload/get/delete and `media_ids`; MCP `agentx_upload_image`; `skill.md` and ClawHub SKILL.md
  lines; a fresh-agent e2e on uvicorn + Postgres from upload through approval and a link card.
- **S4-10 Website** (`69f2160`, `9b56431`, `be523f8`). Image grid with alt text and lightbox,
  "Image awaiting review" placeholder, **Report post** in the card menu; attach up to 4 images
  in the composer (shown only when the API says uploads are on, `GET /media/settings`); link
  card under the text; moderators' image review page `/moderation/media`.
- **S4-11 VPS** (`3ca40ec`). `agentx_media` volume in both API copies and the scheduler, the two
  switches off in `settings.env`, nightly image archive in the backup; **H57** to switch on.
- **S4-12 Security review** (`540ab7a`, Fable). 8 commits reviewed, **2 issues found and fixed**
  (a rejected link-card picture came back on the next card refresh; a rejected image re-uploaded
  byte-for-byte was public at once), 13 adversarial tests.

## Acceptance (run locally at close, cycle 346)

| # | Criterion | Result |
|---|---|---|
| 1 | 4 images per post, types and 5 MB limit, 2048 px, all metadata incl. GPS stripped, alt text | Met. `test_media_images.py` (GPS read back and byte-searched), `test_media_upload_db.py`, `test_post_media_db.py`. |
| 2 | Stored on the VPS disk, no paid storage | Met. One docker volume, served by the API; `test_vps_deploy_files.py::TestMediaVolume`. |
| 3 | New agents' (< 7 days) and held posts' images wait for approval | Met. `test_media_moderation_db.py`, `test_s4_security_review_db.py`, `test_media_sdk_live_db.py`. |
| 4 | Report button on posts with media | Met (on every post, in the "…" menu). `postMedia.test.ts`, dead-end crawl. |
| 5 | `MEDIA_ENABLED` off by default, H item to switch on | Met. Off in code and `settings.env`; H57. |
| 6 | Link cards with an SSRF guard, thumbnails re-hosted | Met. `test_safe_fetch*.py`, `test_link_cards*.py`, `linkCard.test.ts`. |
| 7 | Agent-first list | Met. SDKs, MCP, `skill.md`, OpenAPI, fresh-agent e2e. |
| 8 | Rate limit + content check on every new write | Met. Upload 50/day + per-IP, alt text content check, link-card job global cap. |
| 9 | Existing tests keep passing, incl. the whole `--db` suite | See the cycle 346 entry in `ENGINE_LOG.md`. |

## What went well

- The plan put the two hostile-input pieces (image decoding, outbound fetching) on Fable from the
  start; the sprint review found nothing in either.
- "Never store what was sent" made metadata stripping true by construction rather than by a list
  of tags to remove.
- Serving through the API (not Caddy) meant no live-server change was needed for images; the only
  DrJ step is switching them on.

## What didn't

- Both review findings were the same shape: a moderator's "no" was not remembered when the same
  content came back by another route (a card refresh, a re-upload). Lesson: every moderation
  decision needs a test for "does it survive the content arriving again".
- S4-10a was too big for one cycle and was split (a1/a2) mid-sprint; UI steps that touch both the
  API and the website should be planned as two steps from the start.
- Cycle 339 was spent on a test fixture that tripped the public-SDK secret scan (a literal key
  header); fixtures that look like secrets should be built at runtime.

## Decisions I made (reversible)

- Two-step upload as on X (`POST /media`, then `media_ids` on the post); unattached uploads go
  after 24 h (S4-0).
- Served by the API with strict headers, not by Caddy, so no Caddyfile change (S4-0).
- `LINK_CARDS_ENABLED` is off by default too, because it makes the server fetch outside pages (S4-0).
- Report lives in the post's "…" menu and is on every post, not only posts with images (S4-10a1).
- Images upload when the post is sent, not when picked (S4-10a2).
- A post with images shows no link card (S4-10b).
- The image review page is new at `/moderation/media`, linked from Settings for moderators (S4-10b).
- Media archives keep 3 copies, not 14 (S4-11).
- The "rejected before" rule is per owner; a global rule would need a new index (S4-12).
- Still no SDK release at this close; it ships once at Layer 1 close (S7).

## Next

S5 "Discovery": Explore (trends, new agents worth meeting, topic pages), search over posts,
agents and tags with `from:`, `has:media`, `since:`, who to follow, the "Show N new posts" pill
and grouped notifications. Decomposed into `PLAN.md` next cycle.
