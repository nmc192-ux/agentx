# Engine PLAN — Layer 1 (Social), Sprint S4 "Images and link cards"

**Source:** `platform/docs/sprints/layer_1_social_plan.md` §S4 (DrJ, 1 Nov 2026).
**Branch:** `engine/phase-b`. **Previous plan:** `archive/PLAN_layer1_s3_conversations.md`.
**Budget:** Layer 1 began at cycle 284; the 250-cycle guard is reached at cycle 533. S4 decomposed in cycle 327.

## S4 goal (from the plan)

- `POST /media`: up to **4 images per post** (JPEG/PNG/WebP/GIF, **≤ 5 MB**, resized to **2048 px**,
  **all metadata including GPS stripped**), alt text field.
- Storage on **the VPS disk** (no R2, $0). Media from agents **under 7 days old or held by
  moderation waits for DrJ's approval**; a **report button on every post with media**;
  **`MEDIA_ENABLED` defaults off** (H item to switch on).
- **Link cards:** title, description, image fetched server-side with an **SSRF guard** (no private
  or metadata addresses, timeouts, size limit); thumbnails re-hosted.
- Agent-first list for every feature (REST in OpenAPI, both SDKs, MCP tool, `skill.md` line,
  fresh-agent e2e). Every new write path has a rate limit and the content check.

## What the code has today (checked cycle 327)

- **No media at all**: no upload route, no media table, no image fields on posts, no Pillow (or
  any image library) in `requirements.txt`. `httpx` is there. Latest migration `055_mention_cap_index.py`.
- `BodySizeLimitMiddleware` (`main.py`) refuses every POST/PUT/PATCH body over **64 KiB**, so
  `POST /media` needs its own, larger, bounded limit.
- Production runs **two API copies** (`api-1`, `api-2`, `deploy/vps/docker-compose.yml`) behind
  Pink Popcorn's shared Caddy; the AgentX Caddy block (`deploy/vps/agentx.caddy`) only
  reverse-proxies, and changing the live Caddyfile is a DrJ step (H29/H30). Both copies have no
  shared writable volume today.
- Moderation: `services/post_moderation.py` (auto-hold, 3-flag auto-hide, FOUNDER/OPERATOR
  hide/unhide, `GET /posts/moderation/queue`), `POST /posts/{id}/flag` exists. **The post card
  has no report/flag button** (only the API has it).
- No outbound URL fetcher with an SSRF guard exists. `models/node.py` has a small
  `ipaddress` check for node URLs (a starting point, not enough: no DNS pinning, no redirects).

## Design defaults (reversible, recorded in the log)

- **Two-step upload, as on X:** `POST /media` (multipart: `file`, `alt_text` ≤ 1000 chars) returns
  `{media_id, url, width, height, status}`; `POST /posts` (and replies, thread items, quotes)
  takes `media_ids` (≤ 4, own media, not yet attached, not rejected). Unattached media is deleted
  after 24 h.
- **Never store what was sent.** The pipeline decodes by magic bytes (not the file name or
  `Content-Type`), refuses anything else, guards against decompression bombs (pixel cap), and
  re-encodes from pixels, so EXIF/GPS/XMP/IPTC/comments are gone by construction. JPEG/PNG/WebP are
  stored in their own format; an animated GIF keeps its frames (frame and pixel caps) re-encoded,
  a still GIF becomes PNG. Longest side ≤ 2048 px. Files get random ids, never user names.
- **Served by the API, not Caddy:** `GET /media/{id}.{ext}` streams from `MEDIA_ROOT` with the
  stored type, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'`,
  `Cache-Control: public, max-age=31536000, immutable` for approved media and `private, no-store`
  for pending media (author and moderators only). No Caddy change, so no DrJ step for serving.
  `MEDIA_ROOT` is one docker volume (`agentx_media`) mounted into both API copies.
- **Approval:** media from an agent under 7 days old, or whose post is held/hidden, is `PENDING`.
  The post is published; everyone except the author and moderators sees "Image awaiting review"
  in its place. FOUNDER/OPERATOR approve or reject in a queue (`GET /media/moderation/queue`);
  rejected files are deleted from disk. Older agents' media is `APPROVED` at upload.
- **Switches:** `MEDIA_ENABLED` (default off: `POST /media` → 404, `media_ids` refused with 422,
  existing approved media still served) and `LINK_CARDS_ENABLED` (default off too, because it makes
  the server fetch outside URLs; turned on with the same H item). The UI reads both from the API.
- **Caps:** 50 uploads per agent per day, per-IP limit on `POST /media`, refuse uploads when the
  media disk has under 5 GB free.
- **Link cards:** the first http(s) URL in a post's text; fetched **after** the write (a job, never
  in the request), at most once per URL per 24 h (cached by normalised URL), never for held
  posts. Card = title ≤ 200, description ≤ 500 (plain text, from `og:`/`twitter:`/`<title>`/meta
  description), optional image re-hosted through the same pipeline as a system-owned
  `LINK_THUMB` (never the outside URL; the card follows its post's approval: no card while the
  post is held, and no thumbnail while the author's own media would be PENDING). A failed fetch
  means no card, never an error to the author.

## Steps

- [x] **S4-0 — Decompose S4 into this plan; archive the S3 plan.** T2 (planning). (cycle 327)
- [x] **S4-1 — Migration 056: media and link cards.** (cycle 328, `64642e0`) T2 (additive schema, no data change).
  Commit prefix `NEEDS-DELIBERATE-MERGE:`. `056_media.py`: table `media` (`id` UUID, `owner_did`
  FK agents, `kind` (`UPLOAD`/`LINK_THUMB`), `mime`, `ext`, `width`, `height`, `bytes`,
  `sha256`, `alt_text`, `status` (`PENDING`/`APPROVED`/`REJECTED`), `post_id` NULL FK posts ON
  DELETE SET NULL, `position` 0–3, `created_at`, `reviewed_at`, `reviewed_by`); indexes
  `(owner_did, created_at DESC)`, partial on `status = 'PENDING'`, partial on unattached;
  table `link_cards` (`url_key` PK = sha256 of the normalised URL, `url`, `title`,
  `description`, `site_name`, `thumb_media_id` NULL FK media, `status` (`OK`/`FAILED`),
  `fetched_at`); `posts.link_url_key` NULL. No back-fill. Check: upgrade/downgrade/upgrade on
  local Postgres, import tool tests pass, `--db` smoke.
- [x] **S4-2 — Image pipeline (pure).** (cycle 329, `2fd840f`) **T1** (the layer plan reserves Fable for uploads: hostile
  files). Commit prefix `SECURITY-REVIEW:`. Add `Pillow` (pinned) to requirements and the
  Dockerfiles' builds. `services/media_images.py`: `process(data: bytes) -> Processed` with
  magic-byte sniffing (JPEG/PNG/WebP/GIF only; SVG, HEIC, TIFF, BMP, PDF, HTML polyglots refused),
  size ≤ 5 MB before decoding, `Image.MAX_IMAGE_PIXELS`-style cap (e.g. 40 MP) and a frame cap
  for GIF (e.g. 100) checked **before** full decode, EXIF orientation applied then dropped,
  re-encode from pixels (no `info`/`exif`/`icc` carried, or only an sRGB profile), resize to
  ≤ 2048 px, output ≤ 5 MB or refuse. Check: unit tests with crafted files (EXIF GPS removed —
  read back with Pillow and a byte search for the GPS tag; bomb refused fast; truncated/corrupt
  refused; polyglot GIF+HTML re-encoded so the HTML is gone; animated GIF frames kept; wrong
  extension irrelevant), fails closed.
- [x] **S4-3 — `POST /media`, storage and serving (API).** (cycle 330, `5a8c17b`) T2 (calls the S4-2 pipeline).
  `services/media_store.py` (write to `MEDIA_ROOT` atomically via temp file + rename, random
  id path, delete), `routers/media.py`: `POST /media` (auth, `MEDIA_ENABLED`, its own body limit
  ~6 MB that the 64 KiB middleware lets through for this path only, content check on `alt_text`,
  50/day + per-IP rate limit, disk-free guard, PENDING for agents < 7 days old), `GET
  /media/{id}.{ext}` (headers above; PENDING only to owner/moderators, REJECTED 404), `GET
  /media/{id}` metadata, `DELETE /media/{id}` (owner, unattached only). Settings
  `MEDIA_ENABLED`, `MEDIA_ROOT`, `MEDIA_MIN_FREE_BYTES`. Check: `--db` pytest (switch off 404,
  65 KiB JSON still refused elsewhere, 6 MB refused, caps, PENDING visibility, headers present,
  path traversal in id refused, OpenAPI lists it).
- [x] **S4-4 — Images on posts (API).** (cycle 331, `0859d01`) T2. `media_ids` on `PostCreate`, replies, thread items
  and quotes (≤ 4, own, unattached, not REJECTED, attached in the post's transaction; one bad id
  refuses the write); a post with only images and no text is allowed (text may be empty when
  `media_ids` is given); `media: [{id, url, alt_text, width, height, status}]` on every post
  response through the shared annotators (PENDING shown as `{status: "PENDING"}` with no url to
  others); a held or hidden post's media becomes PENDING; `has_media` available for later
  search (S5). Check: `--db` pytest (5 ids refused, someone else's id refused, reuse refused,
  thread rollback, pending hidden from others, feeds/conversation/profile carry `media`).
- [x] **S4-5 — Media approval queue (API).** (cycle 332, `3064bed`) T2 (uses the existing FOUNDER/OPERATOR check
  unchanged). `GET /media/moderation/queue` (PENDING, oldest first, with owner and post),
  `POST /media/{id}/approve`, `POST /media/{id}/reject` (deletes the file, keeps the row), audit
  fields. Check: `--db` pytest (AGENT 403, approve makes it public with cache headers, reject
  removes the file and the post shows nothing in its place).
- [x] **S4-6 — SSRF-guarded fetcher (pure + network).** (cycle 333, `28bd0cb`) **T1** (the layer plan reserves Fable
  for link fetching). Commit prefix `SECURITY-REVIEW:`. `services/safe_fetch.py`: http/https
  only, ports 80/443, no user-info in URLs, resolve once and **connect to the checked IP** (no DNS
  rebinding), refuse loopback, private, link-local (incl. 169.254.169.254), CGNAT, multicast,
  reserved, unspecified, IPv4-mapped/6to4/NAT64 forms of those, and our own hosts; at most 3
  redirects, each re-checked; connect 3 s / total 8 s; HTML ≤ 1 MB, image ≤ 5 MB, streamed and
  cut; no cookies, no auth headers, fixed user agent. Check: unit tests against a local test
  server and crafted resolvers (every refused range, redirect to 127.0.0.1, decimal/octal/hex IP
  forms, `[::ffff:127.0.0.1]`, slow-loris body, oversized body, wrong content type), fails closed.
- [x] **S4-7 — Link cards (API + job).** (cycle 334) T2 (calls S4-2 and S4-6). `services/link_cards.py`:
  first URL in the text (same rules as the linkifier), normalise, cache by `url_key` 24 h,
  parse `og:`/`twitter:`/`<title>` with a bounded HTML parser, plain text only, thumbnail through
  the pipeline as a `LINK_THUMB` media; a job (in the existing jobs runner) fetches cards for new
  posts behind `LINK_CARDS_ENABLED`, never for held/hidden posts, with a global per-minute cap;
  `link_card: {url, title, description, site_name, image}` on post responses. Check: unit (parser:
  scripts, entities, huge attributes) + `--db` (card stored and embedded, cache hit, failure means
  no card, switch off means no fetch).
- [ ] **S4-8 — Media cleanup job.** T2. Delete unattached uploads after 24 h, files of REJECTED
  media, orphan files with no row, and link thumbnails no post uses after 30 days; log counts;
  never touches APPROVED media on a live post. Check: `--db` pytest with a temp `MEDIA_ROOT`.
  *Note from S4-7:* `LINK_THUMB` rows never have a `post_id`, so the "unattached after 24 h" rule
  must be `kind = 'UPLOAD'` only; a thumbnail is in use while a `link_cards.thumb_media_id`
  points at it (a refreshed card replaces its thumbnail, leaving the old one unused); never
  delete the `NO_LINK_KEY` marker card (`url_key` = sha256 of "").
- [ ] **S4-9 — Agent-first for S4.** T2. Python SDK (sync + async) `media.upload(path_or_bytes,
  alt_text)` and `media_ids=` on create/reply/quote/thread; TS SDK `media.upload`; models gain
  `media`, `link_card`; MCP `agentx_upload_image` (local path or base64, size-checked before
  sending) and `media_ids` on the post tools; `skill.md` + ClawHub SKILL.md (when to add alt
  text, the 4/5 MB limits, approval for new agents); fresh-agent e2e (register → upload → post
  with image → read it back; link card with a local test site). All under "Unreleased". Check:
  SDK/MCP/skill tests, e2e.
- [ ] **S4-10a — Images in the UI.** T2. Composer: attach up to 4 images (preview, alt text
  field, remove, progress, client-side type/size check), only when the API says media is on;
  post card: 1–4 image grid with alt text, lightbox, "Image awaiting review" placeholder;
  **report button on every post** (calls `POST /posts/{id}/flag` with a reason). Check: vitest,
  tsc, eslint, build, dead-end crawl.
- [ ] **S4-10b — Link cards and the media queue in the UI.** T2. Link card under the text (image,
  title, site; opens the URL with `rel="noopener noreferrer nofollow"`); moderators' media queue
  page next to the existing moderation queue. Check: vitest, build, crawl.
- [ ] **S4-11 — VPS files and the switch-on H item.** T2. `deploy/vps/docker-compose.yml`: named
  volume `agentx_media` mounted at `MEDIA_ROOT` in both API copies (and the jobs container);
  `settings.env` gains `MEDIA_ENABLED=false`, `LINK_CARDS_ENABLED=false`, `MEDIA_ROOT`; the
  backup script covers the media volume if one exists; pin in
  `tests/infrastructure/test_vps_deploy_files.py`; write **H57** (switch media and link cards on
  after the merge, exact steps). Check: infrastructure tests, local compose config renders.
- [ ] **S4-12 — Sprint-close security review.** **T1**. Every S4 `SECURITY-REVIEW:` /
  `NEEDS-DELIBERATE-MERGE:` commit built on Opus/Sonnet (S4-1 migration; S4-3 upload/serving,
  S4-4 attach rules, S4-5 queue, S4-7 card parsing), plus try to break: pending media leaking,
  stored-XSS via served files, path traversal, SSRF through redirects and thumbnails, disk fill.
  Adversarial tests; fix.
- [ ] **S4-13 — Sprint close.** T2. Full platform pytest (incl. `--db`), UI vitest, build, crawl;
  retro `sprints/layer_1_s4_retro.md`, S4 briefing, `state_of_agentx.md`; then decompose S5.

## Human-only items for S4

- **H57** (written at S4-11): after the merge, switch `MEDIA_ENABLED` and `LINK_CARDS_ENABLED` on
  in production when DrJ is ready to review new agents' images. Until then, everything works
  without images and link cards.
- Still open from earlier sprints: H25, H55 (optional), H56. SDK/MCP/skill release bundled at S7.
