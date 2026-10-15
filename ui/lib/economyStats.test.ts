// Run with `npm test` (node --test; Node strips the types itself).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  COUNTERS,
  asOfText,
  counterOf,
  isMet,
  ofTarget,
  progressPercent,
  resultFromStatus,
  type EconomyStats,
} from "./economyStats.ts";

const stats: EconomyStats = {
  bounties_posted: { count: 3, target: 10 },
  bounties_paid: { count: 5, target: 5 },
  collectives_by_outsiders: { count: 0, target: 3 },
  outside_agents_joined: { count: 1234, target: 100 },
  outside_agents_posting: { count: 40, target: 100 },
  outside_agents_trusted: { count: 0, target: 1 },
  as_of: "2026-10-15T03:29:00+00:00",
};

test("every API counter has a label and none is listed twice", () => {
  const keys = COUNTERS.map((c) => c.key).sort();
  assert.deepEqual(keys, Object.keys(stats).filter((k) => k !== "as_of").sort());
  for (const c of COUNTERS) assert.ok(c.label && c.blurb);
});

test("n of target, with thousands separators", () => {
  assert.equal(ofTarget(counterOf(stats, "bounties_posted")), "3 of 10");
  assert.equal(ofTarget(counterOf(stats, "outside_agents_joined")), "1,234 of 100");
});

test("progress is 0–100 and a met target is full", () => {
  assert.equal(progressPercent({ count: 3, target: 10 }), 30);
  assert.equal(progressPercent({ count: 0, target: 3 }), 0);
  assert.equal(progressPercent({ count: 1234, target: 100 }), 100);
  assert.equal(progressPercent({ count: 0, target: 0 }), 0);
  assert.equal(progressPercent({ count: 2, target: 0 }), 100);
  assert.equal(isMet({ count: 5, target: 5 }), true);
  assert.equal(isMet({ count: 4, target: 5 }), false);
  assert.equal(isMet({ count: 0, target: 0 }), false);
});

test("odd values from the API read as zero, never NaN or negative", () => {
  const odd = { ...stats, bounties_posted: { count: -2, target: Number.NaN } } as EconomyStats;
  assert.deepEqual(counterOf(odd, "bounties_posted"), { count: 0, target: 0 });
  const missing = { ...stats } as Partial<EconomyStats>;
  delete missing.bounties_paid;
  assert.deepEqual(counterOf(missing as EconomyStats, "bounties_paid"), { count: 0, target: 0 });
  assert.deepEqual(counterOf({ ...stats, bounties_paid: { count: 2.7, target: 5 } }, "bounties_paid"), { count: 2, target: 5 });
});

test("as_of is shown in UTC, and a bad timestamp shows nothing", () => {
  assert.equal(asOfText(stats.as_of), "15 Oct 2026, 03:29 UTC");
  assert.equal(asOfText("not a date"), "");
  assert.equal(asOfText(null), "");
});

test("404 means switched off; other failures and bad bodies are errors", () => {
  assert.deepEqual(resultFromStatus(404, null), { state: "off" });
  assert.deepEqual(resultFromStatus(200, stats), { state: "on", stats });
  assert.deepEqual(resultFromStatus(503, null), { state: "error" });
  assert.deepEqual(resultFromStatus(429, null), { state: "error" });
  assert.deepEqual(resultFromStatus(200, null), { state: "error" });
  assert.deepEqual(resultFromStatus(200, { detail: "x" }), { state: "error" });
});
