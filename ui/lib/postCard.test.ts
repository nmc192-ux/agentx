// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 (S2-8): one post card everywhere, with a trust badge only from
// 0.75, the founder line only for founders, the @handle, and exactly the
// four built actions (reply, repost, like, share).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  POST_CARD_ACTIONS, TRUST_BADGE_MIN, avatarHue, avatarInitials, cardAuthor,
  shortTimeAgo, trustBadge,
} from "./postCard.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const CARD = read("../components/feed/PostCard.tsx");

test("the trust badge shows from 0.75 only, never as a number", () => {
  assert.equal(TRUST_BADGE_MIN, 0.75);
  for (const t of [0, 0.5, 0.7499, null, undefined, Number.NaN]) assert.equal(trustBadge(t), null, String(t));
  for (const t of [0.75, 0.9, 1]) {
    const b = trustBadge(t);
    assert.ok(b, String(t));
    assert.equal(b.label, "Trusted");
    assert.ok(b.tooltip.length > 20);
    assert.doesNotMatch(`${b.label} ${b.tooltip}`, /\d/);
  }
});

test("the byline: name, @handle, and the founder line only when the server sends it", () => {
  const nova = cardAuthor({
    author_did: "did:agentx:nova-001", author_name: "Nova", author_handle: "nova",
    author_operator_label: "Founding agent, operated by AgentX",
  });
  assert.equal(nova.name, "Nova");
  assert.equal(nova.handle, "@nova");
  assert.equal(nova.operatorLine, "Founding agent, operated by AgentX");
  assert.equal(nova.profileHref, "/agents/did%3Aagentx%3Anova-001");

  const outsider = cardAuthor({ author_did: "did:agentx:nova-002", author_name: "Nova", author_handle: "nova_002" });
  assert.equal(outsider.operatorLine, null);
  assert.equal(outsider.handle, "@nova_002");

  const bare = cardAuthor({ author_did: "did:agentx:old-001", author_name: null, author_handle: "  ", author_operator_label: "" });
  assert.equal(bare.name, "old-001");
  assert.equal(bare.handle, null);
  assert.equal(bare.operatorLine, null);
});

test("avatar initials and colour are stable per author", () => {
  assert.equal(avatarInitials("Nova"), "NO");
  assert.equal(avatarInitials("@#"), "?");
  assert.equal(avatarHue("did:agentx:a-001"), avatarHue("did:agentx:a-001"));
  assert.ok(avatarHue("did:agentx:a-001") >= 0 && avatarHue("did:agentx:a-001") < 360);
});

test("time is short", () => {
  const now = Date.parse("2026-11-02T12:00:00Z");
  assert.equal(shortTimeAgo("2026-11-02T11:59:30Z", now), "now");
  assert.equal(shortTimeAgo("2026-11-02T11:55:00Z", now), "5m");
  assert.equal(shortTimeAgo("2026-11-02T09:00:00Z", now), "3h");
  assert.equal(shortTimeAgo("2026-10-31T12:00:00Z", now), "2d");
  assert.equal(shortTimeAgo("junk", now), "");
});

test("the card's action row is exactly reply, repost, like, share", () => {
  assert.deepEqual([...POST_CARD_ACTIONS], ["reply", "repost", "like", "share"]);
  const shown = [...CARD.matchAll(/data-action="([a-z]+)"/g)].map((m) => m[1]);
  // Reply appears twice (a link in threads, a button elsewhere); order is the rule.
  assert.deepEqual([...new Set(shown)], [...POST_CARD_ACTIONS]);
});

test("no button for an unbuilt feature, no trust percentage", () => {
  assert.doesNotMatch(CARD, /Start Room|createRoom|FEATURE_ROOMS/);
  assert.doesNotMatch(CARD, /TrustDot|\* 100\)\.toFixed/);
  assert.doesNotMatch(CARD, /vote_count/);
  assert.match(CARD, /trustBadge\(/);
  assert.match(CARD, /operatorLine/);
  assert.match(CARD, /author\.handle/);
});

test("every post list uses the one card", () => {
  assert.match(read("../components/feed/FeedList.tsx"), /<PostCard\b/);
  for (const page of ["../app/LiveFeed.tsx", "../app/explore/page.tsx", "../app/tag/[name]/page.tsx"]) {
    assert.match(read(page), /<FeedList\b/, page);
  }
  assert.match(read("../app/agents/[did]/AgentProfileClient.tsx"), /<PostCard\b/);
  assert.match(read("../app/post/[id]/page.tsx"), /<PostCard post=\{root\}[^>]*detail/);
  assert.match(read("../components/feed/InlineThread.tsx"), /<PostCard\b/);
});
