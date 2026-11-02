// Run with `npm test` (node --test; Node strips the types itself).
// Layer 1 (S2-10b): notifications and DMs name people by @handle.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { atHandle, counterpartyHandle, notifPerson, personHref, personLabel } from "./people.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("a handle shows as @handle, once", () => {
  assert.equal(atHandle("nova_002"), "@nova_002");
  assert.equal(atHandle("@nova_002"), "@nova_002");
  assert.equal(atHandle("  "), null);
  assert.equal(atHandle(null), null);
});

test("label falls back from handle to name to short DID to Someone", () => {
  assert.equal(personLabel({ did: "did:agentx:a-1", name: "Ada", handle: "ada" }), "@ada");
  assert.equal(personLabel({ did: "did:agentx:a-1", name: "Ada", handle: null }), "Ada");
  assert.equal(personLabel({ did: "did:agentx:a-1", name: " ", handle: null }), "a-1");
  assert.equal(personLabel({ did: null, name: null, handle: null }), "Someone");
});

test("links go to /@handle, else the DID page, else nowhere", () => {
  assert.equal(personHref({ did: "did:agentx:a-1", handle: "ada" }), "/@ada");
  assert.equal(personHref({ did: "did:agentx:a-1" }), "/agents/did%3Aagentx%3Aa-1");
  assert.equal(personHref({}), null);
});

test("a notification reads its sender from the server fields", () => {
  const p = notifPerson({ from_did: "did:agentx:a-1", from_name: "Ada", from_handle: "ada" });
  assert.equal(personLabel(p), "@ada");
  assert.equal(personLabel(notifPerson({ from_did: null, from_name: null })), "Someone");
});

test("the other side of a DM is picked by my DID", () => {
  const m = {
    sender_agent_did: "did:agentx:me", receiver_agent_did: "did:agentx:you",
    sender_handle: "me_1", receiver_handle: "you_1",
  };
  assert.equal(counterpartyHandle(m, "did:agentx:me"), "you_1");
  assert.equal(counterpartyHandle(m, "did:agentx:you"), "me_1");
  assert.equal(counterpartyHandle({ ...m, receiver_handle: null }, "did:agentx:me"), null);
});

test("the pages use the shared rules", () => {
  const notifs = read("../app/notifications/NotificationsClient.tsx");
  assert.match(notifs, /from "@\/lib\/people"/);
  assert.match(notifs, /personLabel\(/);
  const msgs = read("../app/messages/page.tsx");
  assert.match(msgs, /from "@\/lib\/people"/);
  assert.match(msgs, /counterpartyHandle\(/);
});
