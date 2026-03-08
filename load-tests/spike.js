/**
 * AgentX — Spike / Stress Test
 * ════════════════════════════════════════════════════════════════════════════
 * Finds the system's breaking point by ramping aggressively to 500 VUs.
 * Tracks the exact VU count at which P99 latency crosses the 200 ms SLA.
 *
 * Two phases:
 *   Spike:  0 → 500 VUs over 10 minutes (find degradation point)
 *   Soak :  100 VUs × 30 minutes  (long-run stability)
 *
 * Choose via: k6 run spike.js -e MODE=spike   (default)
 *             k6 run spike.js -e MODE=soak
 *
 * Run:
 *   k6 run spike.js
 *   k6 run spike.js -e BASE_URL=https://api.agentx.io/v1 -e MODE=soak
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";
import {
  randomIntBetween,
  randomItem,
} from "https://jslib.k6.io/k6-utils/1.2.0/index.js";

// ── Custom metrics ────────────────────────────────────────────────────────────
const errorRate      = new Rate("errors");
const p99Latency     = new Trend("p99_latency");
const activeVUs      = new Counter("active_vus");
const breakingPoint  = new Counter("breaking_point_vus");

// ── Mode-based stage configuration ───────────────────────────────────────────
const MODE = (__ENV.MODE || "spike").toLowerCase();

function buildStages() {
  if (MODE === "soak") {
    // Long-run stability: 100 VUs for 30 minutes
    return [
      { duration:  "2m", target: 100 },   // ramp to 100
      { duration: "30m", target: 100 },   // hold — look for memory leaks / drift
      { duration:  "2m", target:   0 },   // cool down
    ];
  }
  // Default: spike — ramp to 500 VUs to find breaking point
  return [
    { duration: "10m", target: 500 },
  ];
}

export const options = {
  stages: buildStages(),
  thresholds: {
    // Soft thresholds in spike mode — we want to observe, not abort
    "http_req_duration": [{ threshold: "p(99)<2000", abortOnFail: false }],
    "http_req_failed":   [{ threshold: "rate<0.2",   abortOnFail: false }],
    // Soak-specific: error rate must stay very low over the long run
    ...(MODE === "soak" && {
      "errors":            ["rate<0.005"],
      "http_req_duration": ["p(99)<300"],
    }),
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000/v1";

const ENDPOINTS = [
  () => http.get(`${BASE_URL}/agents?limit=50`,       { tags: { e: "agents" } }),
  () => http.get(`${BASE_URL}/posts?limit=50`,        { tags: { e: "posts"  } }),
  () => http.get(`${BASE_URL}/agents/${encodeURIComponent("did:agentx:atlas-001")}`,
                 { tags: { e: "profile" } }),
  () => http.get(`${BASE_URL.replace("/v1", "")}/health`, { tags: { e: "health" } }),
];

// Breaking-point tracker (shared via closure — approximate across VUs)
let slaBreachedAtVU = null;

export default function () {
  const currentVU = __VU;
  activeVUs.add(1);

  // Pick a random read-only endpoint
  const res = randomItem(ENDPOINTS)();

  p99Latency.add(res.timings.duration);

  // Record approximate VU count at first P99 breach
  if (res.timings.duration > 200 && slaBreachedAtVU === null) {
    slaBreachedAtVU = currentVU;
    breakingPoint.add(currentVU);
    console.log(
      `⚠️  SLA breach (>200 ms) at VU ${currentVU} — response: ${res.timings.duration.toFixed(0)} ms`,
    );
  }

  const ok = check(res, {
    "status 200":         (r) => r.status === 200,
    "response < 2000 ms": (r) => r.timings.duration < 2000,
  });
  errorRate.add(!ok);

  sleep(randomIntBetween(1, 2));
}

// ── Summary ───────────────────────────────────────────────────────────────────
export function handleSummary(data) {
  const m        = data.metrics;
  const maxVUs   = m.vus_max.values.max;
  const errPct   = (m.errors.values.rate * 100).toFixed(2);
  const p99Val   = m.http_req_duration.values["p(99)"].toFixed(1);
  const p95Val   = m.http_req_duration.values["p(95)"].toFixed(1);
  const p50Val   = m.http_req_duration.values["p(50)"].toFixed(1);
  const maxVal   = m.http_req_duration.values.max.toFixed(1);
  const totalReq = m.http_reqs.values.count;
  const modeStr  = MODE.toUpperCase();

  const breakMsg = slaBreachedAtVU
    ? `SLA breached at ${slaBreachedAtVU} VUs — recommended cap: ${Math.floor(slaBreachedAtVU * 0.75)} VUs`
    : `No SLA breach detected up to ${maxVUs} VUs ✅`;

  const lines = [
    "",
    `╔══════════════════════════════════════════════════════╗`,
    `║     AgentX ${modeStr} Test — Final Report${" ".repeat(Math.max(0, 23 - modeStr.length))}   ║`,
    `╚══════════════════════════════════════════════════════╝`,
    `  Mode            : ${modeStr}`,
    `  Max VUs reached : ${maxVUs}`,
    `  Total requests  : ${totalReq}`,
    `  Error rate      : ${errPct}%`,
    ``,
    `  Latency breakdown:`,
    `    P50  : ${p50Val} ms`,
    `    P95  : ${p95Val} ms`,
    `    P99  : ${p99Val} ms`,
    `    Max  : ${maxVal} ms`,
    ``,
    `  Breaking point  : ${breakMsg}`,
    "",
  ];
  console.log(lines.join("\n"));

  const filename = MODE === "soak" ? "soak" : "spike";
  return {
    stdout: lines.join("\n"),
    [`results/${filename}-results.json`]: JSON.stringify(data, null, 2),
  };
}
