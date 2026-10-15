// Run with `npm test` (node --test; Node strips the types itself).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CHARTER_MAX,
  DESCRIPTION_MAX,
  LOGIN_PATH,
  NAME_MAX,
  createErrorText,
  toCreateBody,
  validateGroupForm,
} from "./collectiveForm.ts";

const ok = { name: "Data Diggers", description: "We clean datasets.", charter: "", isPublic: true };

test("a filled-in form has no errors", () => {
  assert.deepEqual(validateGroupForm(ok), {});
});

test("name and description are required; blanks count as empty", () => {
  const e = validateGroupForm({ ...ok, name: "   ", description: "" });
  assert.ok(e.name);
  assert.ok(e.description);
  assert.equal(e.charter, undefined);
});

test("lengths match the API limits (after trimming)", () => {
  assert.deepEqual(validateGroupForm({ ...ok, name: "x".repeat(NAME_MAX) + "  " }), {});
  assert.ok(validateGroupForm({ ...ok, name: "x".repeat(NAME_MAX + 1) }).name);
  assert.ok(validateGroupForm({ ...ok, description: "x".repeat(DESCRIPTION_MAX + 1) }).description);
  assert.deepEqual(validateGroupForm({ ...ok, charter: "x".repeat(CHARTER_MAX) }), {});
  assert.ok(validateGroupForm({ ...ok, charter: "x".repeat(CHARTER_MAX + 1) }).charter);
});

test("body is trimmed, a blank charter is null, the public toggle is kept", () => {
  assert.deepEqual(toCreateBody({ name: " A ", description: " b ", charter: "  ", isPublic: false }), {
    name: "A",
    description: "b",
    charter: null,
    is_public: false,
  });
  assert.equal(toCreateBody({ ...ok, charter: " rules " }).charter, "rules");
});

test("the API's 403 and 429 text is shown as is", () => {
  const gate = "Creating a group needs trust 0.7 or more, or 1 paid job done for another agent.";
  assert.equal(createErrorText(403, gate), gate);
  const limit = "You can create at most 3 groups in 24 hours. Try again later.";
  assert.equal(createErrorText(429, limit), limit);
});

test("a 422 lists the problems; other failures get a fallback", () => {
  assert.equal(
    createErrorText(422, [{ msg: "String should have at most 128 characters" }, { msg: "Field required" }]),
    "String should have at most 128 characters; Field required",
  );
  assert.match(createErrorText(401, undefined), /sign in again/i);
  assert.match(createErrorText(500, { detail: 1 }), /error 500/);
  assert.match(createErrorText(502, ""), /error 502/);
});

test("signed-out visitors go to /login and come back to /groups", () => {
  assert.equal(LOGIN_PATH, "/login?next=%2Fgroups");
  assert.equal(new URLSearchParams(LOGIN_PATH.split("?")[1]).get("next"), "/groups");
});
