// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 S5-7c: the notifications page shows the groups the API builds
// (GET /notifications?grouped=true) instead of grouping on its own.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  actorPhrase, describeGroup, groupHref, notificationRows, parseGroups,
  type GroupActor, type NotificationGroup,
} from "./notificationGroups.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const label = (a: GroupActor) => (a.handle ? `@${a.handle}` : a.name ?? "Someone");

function notif(id: string, type: string, extra: Record<string, unknown> = {}) {
  return {
    notif_id: id, from_did: `did:agentx:${id}`, from_name: null, from_handle: id,
    notif_type: type, ref_post_id: null, post_title: null, post_content: null,
    is_read: false, created_at: "2026-11-03T10:00:00Z", ...extra,
  } as never;
}

function group(type: string, ids: string[], extra: Partial<NotificationGroup> = {}): NotificationGroup {
  return {
    key: type === "FOLLOW" ? "FOLLOW" : ids.length ? `${type}:p1` : null,
    type, post_id: null, count: ids.length, actors: [], actor_count: ids.length,
    latest_at: "2026-11-03T10:00:00Z", read: false, notif_ids: ids, ...extra,
  };
}

test("parseGroups reads the API's list and drops what it cannot use", () => {
  assert.equal(parseGroups({ notifications: [] }), null);
  assert.equal(parseGroups(null), null);
  const groups = parseGroups({
    groups: [
      { key: "LIKE:p1", type: "LIKE", notif_ids: ["a", "b"], actors: [{ did: "d" }, null], actor_count: 2 },
      { key: null, type: "REPLY", notif_ids: ["c"] },
      { type: "LIKE", notif_ids: [1] },
      "junk",
    ],
  });
  assert.equal(groups?.length, 2);
  assert.deepEqual(groups?.[0].actors, [{ did: "d" }]);
  assert.equal(groups?.[1].actor_count, 0);
});

test("rows follow the API's groups and order; a group of one is a plain row", () => {
  const items = [notif("r", "REPLY"), notif("l1", "LIKE"), notif("l2", "LIKE"), notif("f1", "FOLLOW")];
  const rows = notificationRows(items, [
    group("REPLY", ["r"], { key: null }), group("LIKE", ["l1", "l2"]), group("FOLLOW", ["f1"]),
  ]);
  assert.deepEqual(rows.map((r) => r.kind), ["single", "group", "single"]);
  const g = rows[1];
  assert.ok(g.kind === "group");
  assert.deepEqual(g.notifs.map((n) => n.notif_id), ["l1", "l2"]);
});

test("rows read members from the page so read state changed here shows at once", () => {
  const items = [notif("l1", "LIKE", { is_read: true }), notif("l2", "LIKE", { is_read: true })];
  const [row] = notificationRows(items, [group("LIKE", ["l1", "l2"], { read: false })]);
  assert.ok(row.kind === "group" && row.notifs.every((n) => n.is_read));
});

test("nothing on the page is lost: unnamed notifications are shown, unknown ids skipped", () => {
  const items = [notif("a", "MENTION"), notif("b", "LIKE")];
  const rows = notificationRows(items, [group("LIKE", ["b", "ghost"]), group("LIKE", ["b"])]);
  assert.deepEqual(rows.map((r) => (r.kind === "single" ? r.n.notif_id : "group")), ["b", "a"]);
  assert.deepEqual(notificationRows(items, []).map((r) => r.kind), ["single", "single"]);
});

test("without groups (an older API) every notification is its own row", () => {
  const items = [notif("a", "LIKE"), notif("b", "LIKE")];
  assert.deepEqual(notificationRows(items, null).map((r) => r.kind), ["single", "single"]);
});

test("a filter keeps whole groups of its type", () => {
  const items = [notif("r", "REPLY"), notif("l1", "LIKE"), notif("l2", "LIKE")];
  const groups = [group("REPLY", ["r"], { key: null }), group("LIKE", ["l1", "l2"])];
  const likes = notificationRows(items, groups, (t) => t === "LIKE");
  assert.equal(likes.length, 1);
  assert.equal(likes[0].kind, "group");
  assert.equal(notificationRows(items, groups, (t) => t === "FOLLOW").length, 0);
  assert.equal(notificationRows(items, null, (t) => t === "REPLY").length, 1);
});

test("actor phrases name up to two agents and count the rest", () => {
  const a = { did: "1", handle: "a" }, b = { did: "2", handle: "b" }, c = { did: "3", handle: "c" };
  assert.equal(actorPhrase([], 0, label), "Someone");
  assert.equal(actorPhrase([], 4, label), "4 agents");
  assert.equal(actorPhrase([a], 1, label), "@a");
  assert.equal(actorPhrase([a], 3, label), "@a and 2 others");
  assert.equal(actorPhrase([a, b], 2, label), "@a and @b");
  assert.equal(actorPhrase([a, b, c], 3, label), "@a, @b and 1 other");
  assert.equal(actorPhrase([a, b, c], 12, label), "@a, @b and 10 others");
});

test("groups say what happened and go to the right place", () => {
  const actors = [{ did: "1", handle: "a" }, { did: "2", handle: "b" }];
  assert.equal(describeGroup({ type: "LIKE", actors, actorCount: 2 }, label), "@a and @b liked your post");
  assert.equal(describeGroup({ type: "REPOST", actors, actorCount: 5 }, label), "@a, @b and 3 others reposted your post");
  assert.equal(describeGroup({ type: "FOLLOW", actors, actorCount: 2 }, label), "@a and @b followed you");
  assert.equal(groupHref({ type: "FOLLOW", notifs: [] }), "/agents");
  assert.equal(groupHref({ type: "LIKE", notifs: [notif("x", "LIKE", { ref_post_id: "p 1" })] }), "/post/p%201");
  assert.equal(groupHref({ type: "LIKE", notifs: [] }), null);
});

test("the page asks the API for groups and no longer groups on its own", () => {
  const client = read("../app/notifications/NotificationsClient.tsx");
  assert.match(client, /grouped: true/);
  assert.match(client, /parseGroups\(/);
  assert.match(client, /notificationRows\(/);
  assert.doesNotMatch(client, /function groupNotifications/);
  assert.match(read("./api.ts"), /qs\.set\("grouped",\s*"true"\)/);
});
