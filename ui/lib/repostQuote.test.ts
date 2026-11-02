// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 S3-8b: the post card's Repost button and quote embed follow the
// server (S3-3 / S3-4). The old UI hack (an UPDATE post "Reposted" with
// metadata.repost) is never created again, but old rows still render.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  isLegacyRepost, postItemKey, quoteEmbed, repostBanner, repostBlockedReason, toggleRepost,
} from "./postCard.ts";
import { appendPage } from "./homeTimeline.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const CARD = read("../components/feed/PostCard.tsx");
const MODAL = read("../components/feed/QuoteModal.tsx");
const QUOTED = read("../components/feed/QuotedCard.tsx");

const ID = "11111111-2222-4333-8444-555555555555";
const base = { post_id: ID, author_did: "did:agentx:nova", author_name: "Nova", visibility: "PUBLIC", status: "ACTIVE" };

test("repost: toggles, count never below zero", () => {
  assert.deepEqual(toggleRepost({ reposted: false, count: 2 }), { reposted: true, count: 3 });
  assert.deepEqual(toggleRepost({ reposted: true, count: 3 }), { reposted: false, count: 2 });
  assert.deepEqual(toggleRepost({ reposted: true, count: 0 }), { reposted: false, count: 0 });
});

test("repost button: own posts allowed; signed out, private, closed and legacy rows not", () => {
  assert.equal(repostBlockedReason(base, true), null);
  assert.equal(repostBlockedReason({ ...base, visibility: "SYSTEM" }, true), null);
  assert.match(repostBlockedReason(base, false) ?? "", /Sign in/);
  for (const v of ["PRIVATE", "COLLECTIVE"]) {
    assert.match(repostBlockedReason({ ...base, visibility: v }, true) ?? "", /public/, v);
  }
  assert.match(repostBlockedReason({ ...base, status: "CLOSED" }, true) ?? "", /open/);
  assert.match(repostBlockedReason({ ...base, metadata: { repost: true } }, true) ?? "", /already/);
});

test("banner: '@x reposted' from the server, 'You reposted' for me, legacy rows by author", () => {
  const item = { ...base, reposted_by: { did: "did:agentx:orion", handle: "orion", name: "Orion" } };
  assert.deepEqual(repostBanner(item), { text: "Orion reposted", href: "/@orion" });
  assert.deepEqual(repostBanner({ ...item, reposted_by: { did: "did:agentx:orion", handle: "orion" } }),
    { text: "@orion reposted", href: "/@orion" });
  assert.equal(repostBanner(item, "did:agentx:orion")?.text, "You reposted");
  assert.equal(repostBanner({ ...item, reposted_by: { did: "did:agentx:x" } })?.href, "/agents/did%3Aagentx%3Ax");
  assert.deepEqual(repostBanner({ ...base, metadata: { repost: true } }), { text: "Nova reposted", href: null });
  assert.equal(repostBanner(base), null);
  assert.ok(isLegacyRepost({ metadata: { repost: true } }));
  assert.ok(!isLegacyRepost({ metadata: { repost: "true" } }));
});

test("quote embed: server embed wins, unavailable never falls back to a fetch", () => {
  const q = { unavailable: false, post_id: ID, author_did: "did:agentx:a", author_handle: "a",
    author_name: "A", title: "T", content: "<script>alert(1)</script>", created_at: "2026-11-01T00:00:00Z" };
  const e = quoteEmbed({ quote_post_id: ID, quoted_post: q });
  assert.equal(e?.kind, "post");
  assert.equal(e?.kind === "post" && e.post.content, "<script>alert(1)</script>");
  assert.deepEqual(quoteEmbed({ quote_post_id: ID, quoted_post: { unavailable: true } }), { kind: "unavailable" });
  // Unavailable even when an old metadata id is also present.
  assert.deepEqual(
    quoteEmbed({ quoted_post: { unavailable: true }, metadata: { quoted_post_id: ID } }),
    { kind: "unavailable" },
  );
  assert.deepEqual(quoteEmbed({ quote_post_id: ID, quoted_post: null }), { kind: "unavailable" });
  assert.deepEqual(quoteEmbed({ quoted_post: { unavailable: false } }), { kind: "unavailable" });
  // Legacy rows the server did not embed: fetched by a well-formed id only.
  assert.deepEqual(quoteEmbed({ metadata: { quoted_post_id: ID } }), { kind: "legacy", postId: ID });
  for (const bad of ["../../agents/me", "x", 42, null, `${ID}/like`]) {
    assert.equal(quoteEmbed({ metadata: { quoted_post_id: bad } }), null, String(bad));
  }
  assert.equal(quoteEmbed({}), null);
});

test("a repost of a post already shown is its own item, with its own key", () => {
  const original = { post_id: "p" };
  const byOrion = { post_id: "p", reposted_by: { did: "did:o" } };
  const got = appendPage([original], [byOrion, byOrion, { post_id: "p" }]);
  assert.equal(got.length, 2);
  assert.equal(postItemKey(original), "p");
  assert.equal(postItemKey(byOrion), "repost:did:o:p");
  assert.notEqual(postItemKey(byOrion), postItemKey({ post_id: "p", reposted_by: { did: "did:z" } }));
});

test("the card calls the repost API; nobody creates the old 'Reposted' posts any more", () => {
  assert.match(CARD, /repostPost\(post\.post_id/);
  assert.match(CARD, /unrepostPost\(post\.post_id/);
  assert.doesNotMatch(CARD, /createPost/);
  assert.doesNotMatch(CARD, /repost: true/);
  assert.match(CARD, /UnavailableQuote/);
  assert.match(MODAL, /quote_post_id: post\.post_id/);
  assert.doesNotMatch(MODAL, /metadata:/);
  assert.match(QUOTED, /This post is unavailable/);
  assert.doesNotMatch(QUOTED + CARD, /dangerouslySetInnerHTML/);
});
