// Run with `npm test` (node --test; Node strips the types itself).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  JOIN_MESSAGE_MAX,
  actionErrorText,
  canManageRequests,
  joinMessageBody,
  joinMessageError,
  loginPathFor,
  looksLikeUuid,
  membershipAction,
  sortedCounts,
  statusLabel,
} from "./collectivePage.ts";

const ID = "3f2b8c1e-4d5a-4b6c-9e7f-0a1b2c3d4e5f";

test("membership action follows the caller's own standing", () => {
  assert.equal(membershipAction(false, null), "signin");
  assert.equal(membershipAction(false, { role: "OWNER", status: "ACTIVE" }), "signin");
  assert.equal(membershipAction(true, null), "loading");
  assert.equal(membershipAction(true, { role: null, status: "none" }), "ask");
  assert.equal(membershipAction(true, { role: "MEMBER", status: "PENDING" }), "pending");
  assert.equal(membershipAction(true, { role: "MEMBER", status: "ACTIVE" }), "leave");
  assert.equal(membershipAction(true, { role: "ADMIN", status: "ACTIVE" }), "leave");
  assert.equal(membershipAction(true, { role: "OWNER", status: "ACTIVE" }), "owner");
  assert.equal(membershipAction(true, { role: "MEMBER", status: "BANNED" }), "banned");
});

test("only an ACTIVE owner or admin manages requests", () => {
  assert.equal(canManageRequests(null), false);
  assert.equal(canManageRequests({ role: "OWNER", status: "ACTIVE" }), true);
  assert.equal(canManageRequests({ role: "ADMIN", status: "ACTIVE" }), true);
  assert.equal(canManageRequests({ role: "MEMBER", status: "ACTIVE" }), false);
  assert.equal(canManageRequests({ role: "ADMIN", status: "PENDING" }), false);
  assert.equal(canManageRequests({ role: "OWNER", status: "BANNED" }), false);
  assert.equal(canManageRequests({ role: null, status: "none" }), false);
});

test("join note: trimmed, blank is null, too long refused", () => {
  assert.equal(joinMessageBody("  hi there "), "hi there");
  assert.equal(joinMessageBody("   "), null);
  assert.equal(joinMessageError("x".repeat(JOIN_MESSAGE_MAX)), null);
  assert.match(joinMessageError("x".repeat(JOIN_MESSAGE_MAX + 1)) ?? "", /at most 500/);
});

test("API refusal text is shown as is, 422 lists problems, else a fallback", () => {
  assert.equal(actionErrorText(403, " Only OWNER or ADMIN "), "Only OWNER or ADMIN");
  assert.equal(actionErrorText(422, [{ msg: "a" }, { msg: "b" }], "x"), "a; b");
  assert.match(actionErrorText(401, undefined, "leave the group"), /Sign in again to leave the group/);
  assert.match(actionErrorText(500, null, "approve the request"), /error 500/);
});

test("status labels and sorted counts", () => {
  assert.equal(statusLabel("in_progress"), "In progress");
  assert.equal(statusLabel("COMPLETED"), "Completed");
  assert.equal(statusLabel(""), "Unknown");
  assert.deepEqual(sortedCounts({ open: 1, completed: 3, assigned: 1, failed: 0 }), [
    ["completed", 3],
    ["assigned", 1],
    ["open", 1],
  ]);
});

test("login path comes back to the group; ids are checked", () => {
  assert.equal(loginPathFor(ID), `/login?next=%2Fgroups%2F${ID}`);
  assert.equal(looksLikeUuid(ID), true);
  assert.equal(looksLikeUuid("not-a-uuid"), false);
  assert.equal(looksLikeUuid(`${ID}/../x`), false);
});
