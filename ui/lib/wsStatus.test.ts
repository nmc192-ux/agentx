// Run with `npm test` (node --test; Node strips the types itself).
import assert from "node:assert/strict";
import { test } from "node:test";

import { WS_LABEL, wsStatusFromLogs } from "./wsStatus.ts";

const log = (...types: string[]) => types.map((type) => ({ type }));

test("a visitor with no token is signed out, not stuck on checking", () => {
  assert.equal(wsStatusFromLogs([], false), "signed_out");
  assert.equal(wsStatusFromLogs(log("API_CALL"), false), "signed_out");
  assert.notEqual(WS_LABEL.signed_out, WS_LABEL.checking);
});

test("a signed-in agent waits for the handshake", () => {
  assert.equal(wsStatusFromLogs([], true), "checking");
  assert.equal(wsStatusFromLogs(log("WS_CONNECT"), true), "checking");
  assert.equal(wsStatusFromLogs(log("WS_RECONNECT"), true), "checking");
});

test("the last WS event decides", () => {
  assert.equal(wsStatusFromLogs(log("WS_CONNECT", "WS_CONNECTED"), true), "connected");
  assert.equal(wsStatusFromLogs(log("WS_CONNECTED", "AGENT_EVENT"), true), "connected");
  assert.equal(wsStatusFromLogs(log("WS_CONNECTED", "WS_DISCONNECT"), true), "disconnected");
  assert.equal(wsStatusFromLogs(log("WS_CONNECT", "WS_ERROR"), true), "disconnected");
});

test("signing out after a connection reads as signed out", () => {
  assert.equal(wsStatusFromLogs(log("WS_CONNECTED", "WS_DISCONNECT"), false), "signed_out");
});
