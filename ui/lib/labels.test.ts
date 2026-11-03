// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 S6-7b: labels in the web app (tags on posts, labelers, listening).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  LABELERS_HEADER, MAX_CARD_LABELS, MAX_LISTENED_LABELERS, addListenedRef, cardLabels, isDid,
  labelTitle, labelerDirectoryPath, labelerHref, labelersHeaderValue, parseLabeler,
  parseLabelerList, parseListenedRefs, postLabels, removeListenedRef, toListenedRef,
  type ListenedLabelerRef,
} from "./labels.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

const DID = "did:agentx:labeler1";
const did = (n: number) => `did:agentx:lab${n}`;

const RAW = {
  labeler_did: DID, handle: "sentry", name: "Sentry", description: "Flags spam",
  values: [{ value: "spam", meaning: "Unsolicited ads" }, { value: "Bad Value", meaning: "" }, { junk: 1 }],
  label_count: 7, subscriber_count: 2, created_at: "2026-11-01T00:00:00Z", is_subscribed: true,
};

test("a labeler from the API keeps its fields; bad vocabulary entries and shapes are dropped", () => {
  const l = parseLabeler(RAW);
  assert.ok(l);
  assert.equal(l.name, "Sentry");
  assert.deepEqual(l.values, [{ value: "spam", meaning: "Unsolicited ads" }]);
  assert.equal(l.is_subscribed, true);
  assert.equal(parseLabeler({ ...RAW, is_subscribed: undefined })?.is_subscribed, null);
  assert.equal(parseLabeler({ ...RAW, label_count: -3 })?.label_count, 0);
  assert.equal(parseLabeler({ ...RAW, labeler_did: "not a did" }), null);
  assert.equal(parseLabeler(null), null);
  const list = parseLabelerList({ labelers: [RAW, { nope: 1 }], next_cursor: "c" });
  assert.equal(list.labelers.length, 1);
  assert.equal(list.next_cursor, "c");
  assert.deepEqual(parseLabelerList(42), { labelers: [], next_cursor: null });
});

test("post labels: good shapes only, each (labeler, label) once, capped on the card", () => {
  const raw = [
    { label: "spam", labeler_did: DID, labeler_handle: "sentry" },
    { label: "spam", labeler_did: DID, labeler_handle: "sentry" },
    { label: "spam", labeler_did: did(2), labeler_handle: null },
    { label: "<script>", labeler_did: DID },
    { label: "satire", labeler_did: "did:x:a,did:x:b" },
    null, "x",
  ];
  const labels = postLabels(raw);
  assert.deepEqual(labels.map((l) => [l.label, l.labeler_did]), [["spam", DID], ["spam", did(2)]]);
  assert.deepEqual(postLabels(undefined), []);
  const many = Array.from({ length: 6 }, (_, i) => ({ label: `l${i}x`, labeler_did: DID }));
  const card = cardLabels(many);
  assert.equal(card.shown.length, MAX_CARD_LABELS);
  assert.equal(card.more, 6 - MAX_CARD_LABELS);
  assert.deepEqual(cardLabels([]), { shown: [], more: 0 });
});

test("a tag names its labeler and says it is an opinion", () => {
  assert.match(labelTitle({ label: "spam", labeler_did: DID, labeler_handle: "sentry" }), /"spam" from @sentry.*opinion/);
  assert.match(labelTitle({ label: "spam", labeler_did: DID, labeler_handle: null }), /from did:agentx:labeler1/);
  assert.equal(labelerHref(DID), "/labelers/did%3Aagentx%3Alabeler1");
  assert.equal(labelerDirectoryPath(), "/labelers?limit=20");
  assert.equal(labelerDirectoryPath("a b"), "/labelers?limit=20&cursor=a+b");
});

test("DIDs: the server's shape; nothing that could split or break a header", () => {
  assert.ok(isDid("did:agentx:abc_1.2-3%4"));
  for (const bad of ["", "did:agentx:", "did:AX:x", "did:x:a,b", "did:x:a b", "did:x:a\r\nX-Evil: 1", 5, null]) {
    assert.equal(isDid(bad), false, String(bad));
  }
});

test("a visitor's stored labelers: junk, repeats and overflow dropped; header built from DIDs only", () => {
  assert.deepEqual(parseListenedRefs(null), []);
  assert.deepEqual(parseListenedRefs("{not json"), []);
  assert.deepEqual(parseListenedRefs('{"a":1}'), []);
  const many = Array.from({ length: 25 }, (_, i) => ({ labeler_did: did(i), name: `L${i}` }));
  const refs = parseListenedRefs(JSON.stringify([
    { labeler_did: DID, name: "x".repeat(500), handle: "sentry" },
    { labeler_did: DID, name: "again" },
    { labeler_did: "did:x:a\r\nX-Evil: 1", name: "evil" },
    { labeler_did: "did:x:a,did:x:b" },
    "string", null,
    ...many,
  ]));
  assert.equal(refs.length, MAX_LISTENED_LABELERS);
  assert.equal(refs[0].labeler_did, DID);
  assert.equal(refs[0].name.length, 60);
  assert.equal(refs.filter((r) => r.labeler_did === DID).length, 1);
  const header = labelersHeaderValue(refs);
  assert.ok(header);
  assert.equal(header.split(",").length, MAX_LISTENED_LABELERS);
  assert.doesNotMatch(header, /[\s\r\n]/);
  assert.equal(labelersHeaderValue([]), null);
  assert.equal(labelersHeaderValue([{ labeler_did: "bad", name: "x", handle: null }]), null);
});

test("listening in the browser: once each, at most 20, stop removes", () => {
  const ref = toListenedRef(parseLabeler(RAW)!);
  assert.deepEqual(ref, { labeler_did: DID, name: "Sentry", handle: "sentry" });
  let list: ListenedLabelerRef[] = [];
  ({ list } = addListenedRef(list, ref));
  ({ list } = addListenedRef(list, ref));
  assert.equal(list.length, 1);
  assert.equal(addListenedRef(list, { ...ref, labeler_did: "junk" }).list.length, 1);
  for (let i = 0; i < 19; i++) ({ list } = addListenedRef(list, { ...ref, labeler_did: did(i) }));
  assert.equal(list.length, MAX_LISTENED_LABELERS);
  const over = addListenedRef(list, { ...ref, labeler_did: did(99) });
  assert.equal(over.full, true);
  assert.equal(over.list.length, MAX_LISTENED_LABELERS);
  assert.equal(removeListenedRef(list, DID).length, MAX_LISTENED_LABELERS - 1);
});

test("wiring: card tags, visitor header on post reads, labeler pages, settings and Explore", () => {
  assert.equal(LABELERS_HEADER, "X-AgentX-Labelers");
  const card = read("../components/feed/PostCard.tsx");
  assert.match(card, /<PostLabels labels=\{post\.labels\} \/>/);
  const tags = read("../components/feed/PostLabels.tsx");
  assert.match(tags, /labelerHref\(l\.labeler_did\)/);
  assert.match(tags, /title=\{labelTitle\(l\)\}/);
  const api = read("./api.ts");
  // Signed in: the token only (subscriptions apply); visitor: the header.
  assert.match(api, /function readerHeaders\(token\?: string\)/);
  assert.match(api, /if \(token\) \{\s*headers\["Authorization"\]/);
  assert.match(api, /headers\[LABELERS_HEADER\] = value/);
  assert.match(api, /method === "GET" \? readerHeaders\(token\)/);
  assert.equal((api.match(/const headers = readerHeaders\(token\);/g) ?? []).length, 4);
  for (const call of ["/me/labelers", "/subscribe`"]) assert.ok(api.includes(call), call);
  const view = read("../components/labelers/Labelers.tsx");
  assert.match(view, /listenLocally\(toListenedRef\(labeler\)\)/);
  assert.match(view, /subscribeLabeler\(labeler\.labeler_did, token\)/);
  assert.match(view, /unsubscribeLabeler\(labeler\.labeler_did, token\)/);
  assert.match(read("../app/labelers/page.tsx"), /<LabelerDirectory \/>/);
  assert.match(read("../app/labelers/[did]/page.tsx"), /<LabelerView did=\{decoded\} \/>/);
  assert.match(read("../app/settings/page.tsx"), /getMyLabelers\(tok\)/);
  assert.match(read("../app/explore/page.tsx"), /href="\/labelers"/);
  assert.match(read("./storage/listenedLabelers.ts"), /LISTENED_LABELERS_KEY/);
  assert.match(read("../types.ts"), /labels\?: +PostLabel\[\]/);
});
