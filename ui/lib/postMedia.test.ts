// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 S4-10a: images on the post card (grid, lightbox, "awaiting
// review") and the "Report post" action. The card only renders the
// server's own /media/ paths; a PENDING image is private to its author and
// the moderators, so it is fetched with the token, never as a plain <img>.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  FLAG_REASONS, MAX_FLAG_NOTE, MAX_POST_MEDIA, PENDING_TEXT, canReport, flagBody, flagResultText,
  gridClass, mediaSrc, mediaTiles, stepIndex, tileClass,
} from "./postMedia.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const CARD = read("../components/feed/PostCard.tsx");
const GRID = read("../components/feed/PostMediaGrid.tsx");
const REPORT = read("../components/feed/ReportPostModal.tsx");
const API = read("./api.ts");
const MODELS = read("../../platform/src/models/post.py");
const STORE = read("../../platform/src/services/media_store.py");

const BASE = "https://api.example.test";
const id = (n: number) => `0000000${n}-aaaa-4bbb-8ccc-dddddddddddd`;
const img = (n: number, over: Record<string, unknown> = {}) => ({
  media_id: id(n), status: "APPROVED", url: `/media/${id(n)}.png`,
  alt_text: `alt ${n}`, width: 800, height: 600, ...over,
});

test("mediaSrc accepts only the server's own /media/{uuid}.{ext} paths", () => {
  assert.equal(mediaSrc(`/media/${id(1)}.png`, BASE), `${BASE}/media/${id(1)}.png`);
  assert.equal(mediaSrc(`/media/${id(1)}.jpg`, `${BASE}/`), `${BASE}/media/${id(1)}.jpg`);
  assert.equal(mediaSrc(`/media/${id(1)}.webp`, ""), `/media/${id(1)}.webp`);
  for (const bad of [
    null, undefined, "", `https://evil.test/media/${id(1)}.png`, `//evil.test/media/${id(1)}.png`,
    "javascript:alert(1)", `/media/${id(1)}.svg`, `/media/${id(1)}.html`, `/media/${id(1)}`,
    `/media/../secrets/${id(1)}.png`, `/media/${id(1)}.png?x=1`, `/media/${id(1)}.png#x`,
    `/media/${id(1).toUpperCase()}.png`, `/posts/${id(1)}.png`, ` /media/${id(1)}.png`,
    `/media/${id(1)}.png\n`, "data:image/png;base64,AAAA",
  ]) {
    assert.equal(mediaSrc(bad as string, BASE), null, String(bad));
  }
});

test("the allowed extensions match the server's", () => {
  for (const ext of ["jpg", "png", "webp", "gif"]) {
    assert.ok(STORE.includes(`"${ext}"`), ext);
    assert.ok(mediaSrc(`/media/${id(1)}.${ext}`, BASE));
  }
});

test("approved images are plain tiles with their alt text, in order", () => {
  const tiles = mediaTiles([img(1), img(2)], BASE);
  assert.deepEqual(tiles.map((t) => t.kind), ["image", "image"]);
  assert.deepEqual(tiles[0], {
    kind: "image", id: id(1), src: `${BASE}/media/${id(1)}.png`, alt: "alt 1",
    width: 800, height: 600, authed: false,
  });
  assert.equal(tiles[1].id, id(2));
});

test("a pending image without a url is the placeholder; with a url it needs the token", () => {
  const hidden = mediaTiles([img(1, { status: "PENDING", url: null, alt_text: null })], BASE);
  assert.deepEqual(hidden, [{ kind: "pending", id: id(1) }]);
  const own = mediaTiles([img(1, { status: "PENDING" })], BASE);
  assert.equal(own[0].kind, "image");
  assert.equal(own[0].kind === "image" && own[0].authed, true);
  assert.equal(PENDING_TEXT, "Image awaiting review");
});

test("rejected, unknown, malformed and outside-url items show nothing", () => {
  const tiles = mediaTiles([
    img(1, { status: "REJECTED" }),
    img(2, { status: "WHATEVER" }),
    img(3, { url: "https://evil.test/x.png" }),
    img(4, { status: "PENDING", url: "https://evil.test/x.png" }),
    null, "x", { status: "APPROVED" },
    img(5, { alt_text: null }),
  ], BASE);
  assert.deepEqual(tiles.map((t) => t.id), [id(5)]);
  assert.equal(tiles[0].kind === "image" && tiles[0].alt, "");
  assert.deepEqual(mediaTiles(undefined, BASE), []);
  assert.deepEqual(mediaTiles(null, BASE), []);
  assert.deepEqual(mediaTiles({}, BASE), []);
});

test("never more than 4 tiles (the server's cap)", () => {
  assert.equal(MAX_POST_MEDIA, 4);
  assert.ok(MODELS.includes("MAX_POST_MEDIA"));
  assert.equal(mediaTiles([1, 2, 3, 4, 5, 6].map((n) => img(n)), BASE).length, 4);
});

test("grid layout for 1 to 4 images", () => {
  assert.equal(gridClass(1), "grid grid-cols-1");
  assert.equal(gridClass(2), "grid grid-cols-2");
  assert.equal(gridClass(3), "grid grid-cols-2 grid-rows-2");
  assert.equal(gridClass(4), "grid grid-cols-2");
  assert.match(tileClass(0, 3), /row-span-2/);
  assert.doesNotMatch(tileClass(1, 3), /row-span-2/);
  assert.match(tileClass(0, 1), /max-h/);
  assert.match(tileClass(3, 4), /aspect/);
});

test("lightbox steps wrap round", () => {
  assert.equal(stepIndex(0, 1, 3), 1);
  assert.equal(stepIndex(2, 1, 3), 0);
  assert.equal(stepIndex(0, -1, 3), 2);
  assert.equal(stepIndex(0, 1, 1), 0);
  assert.equal(stepIndex(0, 1, 0), 0);
});

test("report reasons are exactly the server's PostFlagReason values", () => {
  const block = MODELS.slice(MODELS.indexOf("class PostFlagReason"), MODELS.indexOf("class PostFlagCreate"));
  const server = [...block.matchAll(/=\s*"([a-z_]+)"/g)].map((m) => m[1]).sort();
  assert.deepEqual(FLAG_REASONS.map((r) => r.value).sort(), server);
  assert.ok(MODELS.includes(`max_length=${MAX_FLAG_NOTE})`));
});

test("flagBody: a known reason, an optional trimmed note, nothing over the cap", () => {
  assert.deepEqual(flagBody("spam", ""), { reason: "spam" });
  assert.deepEqual(flagBody("abuse", "  rude  "), { reason: "abuse", note: "rude" });
  assert.equal(flagBody("", "x"), null);
  assert.equal(flagBody("SPAM", ""), null);
  assert.equal(flagBody("nonsense", ""), null);
  assert.ok(flagBody("other", "x".repeat(MAX_FLAG_NOTE)));
  assert.equal(flagBody("other", "x".repeat(MAX_FLAG_NOTE + 1)), null);
});

test("only signed-in readers who are not the author can report", () => {
  assert.equal(canReport(true, false), true);
  assert.equal(canReport(true, true), false);
  assert.equal(canReport(false, false), false);
});

test("report answers are plain words", () => {
  assert.match(flagResultText(null), /moderator/);
  assert.match(flagResultText(409), /already reported/);
  assert.match(flagResultText(400), /cannot report/);
  assert.match(flagResultText(429), /Try again later/);
  assert.match(flagResultText(500), /Could not send/);
});

test("the card shows the grid, and a Report post item in the menu", () => {
  assert.match(CARD, /<PostMediaGrid media=\{post\.media\} \/>/);
  assert.match(CARD, /data-menu="report"/);
  assert.match(CARD, /canReport\(canWrite, isOwnPost\)/);
  assert.match(CARD, /<ReportPostModal postId=\{post\.post_id\}/);
});

test("the grid uses the helpers, the token fetch for pending files, and no outside URLs", () => {
  assert.match(GRID, /mediaTiles\(media, API_BASE\)/);
  assert.match(GRID, /fetchMediaBlob\(tile\.src, token\)/);
  assert.match(GRID, /URL\.revokeObjectURL/);
  assert.match(GRID, /referrerPolicy="no-referrer"/);
  assert.match(GRID, /alt=\{tile\.alt\}/);
  assert.doesNotMatch(GRID, /dangerouslySetInnerHTML/);
  assert.match(API, /export async function flagPost/);
  assert.match(API, /\/posts\/\$\{encodeURIComponent\(postId\)\}\/flag/);
  assert.match(API, /Authorization: `Bearer \$\{token\}`/);
});

test("the report dialog sends through flagBody and shows flagResultText", () => {
  assert.match(REPORT, /flagBody\(reason, note\)/);
  assert.match(REPORT, /flagPost\(postId, body, token\)/);
  assert.match(REPORT, /flagResultText\(/);
  assert.match(REPORT, /maxLength=\{MAX_FLAG_NOTE\}/);
});
