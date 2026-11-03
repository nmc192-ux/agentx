// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 S4-10b: the link card under a post and the moderators' image
// review page. The card never loads anything from the linked site (its
// picture is the server's re-hosted /media/ copy), only http(s) links are
// clickable, and they open with noopener noreferrer nofollow.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  CARD_REL, MAX_CARD_DESCRIPTION, MAX_CARD_SITE, MAX_CARD_TITLE, MODERATOR_ROLES, accountAgeText, isModerator,
  linkCardView, queueErrorText, reviewErrorText, safeLinkHref, showLinkCard,
} from "./linkCard.ts";
import { mediaSrc } from "./postMedia.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const CARD = read("../components/feed/LinkCard.tsx");
const POST_CARD = read("../components/feed/PostCard.tsx");
const PAGE = read("../app/moderation/media/page.tsx");
const SETTINGS = read("../app/settings/page.tsx");
const ROBOTS = read("../app/robots.ts");
const API = read("./api.ts");
const MODELS = read("../../platform/src/models/post.py");
const MEDIA_ROUTER = read("../../platform/src/routers/media.py");
const MODERATION = read("../../platform/src/services/post_moderation.py");
const LINK_CARDS = read("../../platform/src/services/link_cards.py");

const BASE = "https://api.example.test";
const src = (u: unknown) => mediaSrc(typeof u === "string" ? u : null, BASE);
const ID = "00000001-aaaa-4bbb-8ccc-dddddddddddd";
const card = (over: Record<string, unknown> = {}) => ({
  url: "https://www.example.com/article?id=1",
  title: "An article",
  description: "What it is about.",
  site_name: "Example News",
  image: { url: `/media/${ID}.jpg`, width: 1200, height: 630 },
  ...over,
});

test("linkCardView shows title, description, site and the re-hosted picture", () => {
  assert.deepEqual(linkCardView(card(), src), {
    href: "https://www.example.com/article?id=1",
    host: "example.com",
    title: "An article",
    description: "What it is about.",
    site: "Example News",
    imageSrc: `${BASE}/media/${ID}.jpg`,
  });
});

test("linkCardView falls back to the host when the page had no title or site name", () => {
  const v = linkCardView(card({ title: null, site_name: "  ", description: undefined, image: null }), src);
  assert.equal(v?.title, "example.com");
  assert.equal(v?.site, "example.com");
  assert.equal(v?.description, null);
  assert.equal(v?.imageSrc, null);
});

test("linkCardView never shows a picture from outside the server's /media/ paths", () => {
  for (const bad of [
    "https://www.example.com/og.jpg", "//evil.test/x.png", "javascript:alert(1)",
    `/media/${ID}.svg`, "data:image/png;base64,AAAA", `/media/../${ID}.png`, 42, null,
  ]) {
    assert.equal(linkCardView(card({ image: { url: bad, width: 1, height: 1 } }), src)?.imageSrc, null, String(bad));
  }
});

test("only http(s) links without credentials become a card", () => {
  for (const bad of [
    "javascript:alert(1)", "data:text/html,<b>x</b>", "file:///etc/passwd", "ftp://example.com/",
    "https://user:pw@example.com/", "not a url", "", null, 7, `https://e.com/${"a".repeat(2100)}`,
  ]) {
    assert.equal(safeLinkHref(bad), null, String(bad));
    assert.equal(linkCardView(card({ url: bad }), src), null, String(bad));
  }
  assert.deepEqual(safeLinkHref("http://example.org/a b"), { href: "http://example.org/a%20b", host: "example.org" });
  assert.equal(linkCardView(null, src), null);
  assert.equal(linkCardView("https://example.com", src), null);
});

test("card text is plain, single-line and capped at the server's limits", () => {
  const v = linkCardView(card({
    title: `Line one\nline\ttwo\u0000${"t".repeat(400)}`,
    description: "d".repeat(900),
    site_name: "<b>Site</b>",
  }), src)!;
  assert.ok(v.title.startsWith("Line one line two "));
  assert.equal(v.title.length, MAX_CARD_TITLE);
  assert.equal(v.description?.length, MAX_CARD_DESCRIPTION);
  assert.equal(v.site, "<b>Site</b>"); // rendered as text by React, never as HTML
  assert.match(LINK_CARDS, new RegExp(`^MAX_TITLE = ${MAX_CARD_TITLE}$`, "m"));
  assert.match(LINK_CARDS, new RegExp(`^MAX_DESCRIPTION = ${MAX_CARD_DESCRIPTION}$`, "m"));
  assert.match(LINK_CARDS, new RegExp(`^MAX_SITE_NAME = ${MAX_CARD_SITE}\\b`, "m"));
});

test("a post with images shows no link card", () => {
  assert.equal(showLinkCard([{ media_id: ID }], card()), false);
  assert.equal(showLinkCard([], card()), true);
  assert.equal(showLinkCard(undefined, card()), true);
  assert.equal(showLinkCard(undefined, null), false);
  assert.equal(showLinkCard(undefined, undefined), false);
});

test("the card component opens links safely and never sets HTML", () => {
  assert.equal(CARD_REL, "noopener noreferrer nofollow");
  assert.match(CARD, /rel=\{CARD_REL\}/);
  assert.match(CARD, /target="_blank"/);
  assert.match(CARD, /referrerPolicy="no-referrer"/);
  assert.match(CARD, /e\.stopPropagation\(\)/);
  assert.doesNotMatch(CARD, /dangerouslySetInnerHTML/);
  assert.match(CARD, /mediaSrc\(/);
  assert.match(POST_CARD, /showLinkCard\(post\.media, post\.link_card\) && <LinkCard card=\{post\.link_card\} \/>/);
  // The UI type follows the server's LinkCard model.
  for (const field of ["url", "title", "description", "site_name", "image"]) {
    assert.match(MODELS, new RegExp(`class LinkCard\\(BaseModel\\):[\\s\\S]*?\\b${field}:`), field);
  }
});

test("isModerator matches the server's moderator roles exactly", () => {
  assert.match(MODERATION, /MODERATOR_ROLES = \("FOUNDER", "OPERATOR"\)/);
  assert.deepEqual([...MODERATOR_ROLES], ["FOUNDER", "OPERATOR"]);
  assert.equal(isModerator("FOUNDER"), true);
  assert.equal(isModerator("OPERATOR"), true);
  for (const r of ["MEMBER", "OBSERVER", "DELEGATE", "founder", "", null, undefined, 1]) {
    assert.equal(isModerator(r), false, String(r));
  }
});

test("accountAgeText says how new the uploader is", () => {
  const now = Date.parse("2026-11-03T12:00:00Z");
  assert.equal(accountAgeText("2026-11-03T11:30:00Z", now), "just joined");
  assert.equal(accountAgeText("2026-11-03T11:00:00Z", now), "1 hour old");
  assert.equal(accountAgeText("2026-11-02T12:00:00Z", now), "24 hours old");
  assert.equal(accountAgeText("2026-10-31T12:00:00Z", now), "3 days old");
  assert.equal(accountAgeText("2026-11-04T12:00:00Z", now), "just joined");
  assert.equal(accountAgeText(null, now), "account age unknown");
  assert.equal(accountAgeText("garbage", now), "account age unknown");
});

test("review errors are in plain words, keyed on the server's codes", () => {
  for (const code of ["post_hidden", "not_pending", "already_rejected", "media_changed"]) {
    assert.match(MEDIA_ROUTER, new RegExp(`"${code}"`), code);
    const text = reviewErrorText(409, { detail: { code, message: "x" } });
    assert.notEqual(text, reviewErrorText(409, null), code);
  }
  assert.match(reviewErrorText(409, { detail: { code: "post_hidden" } }), /Unhide the post first/);
  assert.equal(reviewErrorText(404, null), "This image no longer exists.");
  assert.match(reviewErrorText(403, null), /FOUNDER and OPERATOR/);
  assert.match(reviewErrorText(500, "x"), /Try again/);
  assert.match(queueErrorText(403), /FOUNDER and OPERATOR/);
  assert.match(queueErrorText(401), /Sign in again/);
  assert.match(queueErrorText(0), /Try again/);
});

test("the review page uses the moderator routes and fetches private files with the token", () => {
  assert.match(MEDIA_ROUTER, /"\/moderation\/queue"/);
  assert.match(MEDIA_ROUTER, /"\/\{media_id\}\/approve"/);
  assert.match(MEDIA_ROUTER, /"\/\{media_id\}\/reject"/);
  assert.match(API, /`\/media\/moderation\/queue\?\$\{qs\}`/);
  assert.match(API, /`\/media\/\$\{encodeURIComponent\(mediaId\)\}\/\$\{decision\}`/);
  assert.match(PAGE, /fetchMediaBlob\(file, token\)/);
  assert.match(PAGE, /mediaSrc\(url, API_BASE\)/);
  assert.match(PAGE, /URL\.revokeObjectURL/);
  assert.doesNotMatch(PAGE, /dangerouslySetInnerHTML/);
  assert.match(PAGE, /href=\{`\/post\/\$\{encodeURIComponent\(item\.post\.post_id\)\}`\}/);
  // Linked from Settings for moderators only, and kept out of search engines.
  assert.match(SETTINGS, /isModerator\(agent\?\.governance_role\) && \(/);
  assert.match(SETTINGS, /href="\/moderation\/media"/);
  assert.match(ROBOTS, /"\/moderation"/);
});
