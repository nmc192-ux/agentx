// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 (S3-8a): only server-resolved @mentions link; #tags and URLs follow
// the server's rules; nothing is ever HTML.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { linkify, type Segment } from "./linkify.ts";

const NOVA = { handle: "nova", did: "did:agentx:nova-1" };
const kinds = (s: Segment[]) => s.map((x) => `${x.kind}:${x.text}`);
const links = (s: Segment[]) => s.filter((x) => x.kind !== "text");
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("a server-resolved mention links to /@handle", () => {
  const s = linkify("hi @nova!", { mentions: [NOVA] });
  assert.deepEqual(kinds(s), ["text:hi ", "mention:@nova", "text:!"]);
  assert.equal((s[1] as { href: string }).href, "/@nova");
  assert.equal((s[1] as { did: string }).did, NOVA.did);
});

test("mention matching ignores case but links the stored handle", () => {
  const s = linkify("@NoVa hello", { mentions: [NOVA] });
  assert.equal(s[0].kind, "mention");
  assert.equal((s[0] as { href: string }).href, "/@nova");
  assert.equal(s[0].text, "@NoVa");
});

test("names the server did not resolve stay plain text", () => {
  assert.deepEqual(kinds(linkify("hi @ghost", { mentions: [NOVA] })), ["text:hi @ghost"]);
  assert.deepEqual(kinds(linkify("hi @nova")), ["text:hi @nova"]); // no list → no link
  assert.deepEqual(kinds(linkify("hi @nova", { mentions: null })), ["text:hi @nova"]);
});

test("e-mails, @@, URL paths and look-alikes are not mentions", () => {
  const opts = { mentions: [NOVA] };
  for (const text of [
    "mail me at x@nova",
    "@@nova",
    "see /@nova",
    "@novа",            // Cyrillic а
    "@nová",            // a + combining acute
    "@nova_is_a_very_long_name_more_than_30",
  ]) {
    assert.deepEqual(links(linkify(text, opts)), [], text);
  }
});

test("a #tag links when it is one of the post's tags", () => {
  const s = linkify("loving #DeFi and #ai", { tags: ["defi"] });
  assert.deepEqual(kinds(s), ["text:loving ", "tag:#DeFi", "text: and #ai"]);
  assert.equal((s[1] as { href: string }).href, "/tag/defi");
});

test("with no tag list, any parsed #tag links (bios, composer preview)", () => {
  assert.deepEqual(kinds(linkify("#rust rocks")), ["tag:#rust", "text: rocks"]);
});

test("digit-only, entity, path, joined and accented hashes are plain text", () => {
  for (const text of ["issue #42", "&#39;", "x.io/#top", "a#b", "##x", "#cafè", "#" + "a".repeat(51)]) {
    assert.deepEqual(links(linkify(text)), [], text);
  }
});

test("a # or @ inside a URL is part of the URL", () => {
  const s = linkify("read https://x.io/p#frag and https://x.io/@nova.", { mentions: [NOVA] });
  assert.deepEqual(kinds(s), [
    "text:read ", "url:https://x.io/p#frag", "text: and ", "url:https://x.io/@nova", "text:.",
  ]);
  assert.deepEqual(links(linkify("www.x.io/#tag")), []);
});

test("only http and https link; other schemes are text", () => {
  for (const text of ["javascript:alert(1)", "data:text/html,<b>x</b>", "https://", "ftp://x.io"]) {
    assert.ok(linkify(text).every((x) => x.kind === "text"), text);
  }
});

test("HTML is just text: segments carry the raw characters", () => {
  const text = `<script>alert("@nova #x")</script><img src=x onerror=alert(1)>`;
  const s = linkify(text, { mentions: [NOVA], tags: ["x"] });
  assert.equal(s.map((x) => x.text).join(""), text);
  for (const seg of s) {
    if (seg.kind !== "text") assert.ok(seg.href.startsWith("/") || seg.href.startsWith("http"), seg.href);
  }
});

test("joined segments always rebuild the original text", () => {
  const text = "a @nova b #t c https://x.io/a). d @ghost #42 e";
  assert.equal(linkify(text, { mentions: [NOVA], tags: ["t"] }).map((x) => x.text).join(""), text);
});

test("linear on hostile input", () => {
  const text = "@".repeat(20000) + "#".repeat(20000) + "a".repeat(20000);
  const t0 = Date.now();
  linkify(text, { mentions: [NOVA] });
  assert.ok(Date.now() - t0 < 1000);
});

test("the renderer never sets inner HTML and the post card passes server data", () => {
  const rich = read("./text/richText.tsx");
  assert.ok(!rich.includes("dangerouslySetInnerHTML"));
  assert.ok(rich.includes("linkify("));
  const card = read("../components/feed/PostCard.tsx");
  assert.match(card, /renderRichText\(post\.content, \{ mentions: post\.mentions, tags: post\.tags \}\)/);
});
