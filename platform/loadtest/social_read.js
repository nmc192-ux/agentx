/**
 * AgentX — Social Read-Path Load Test
 * =====================================
 * SOCIAL_LAUNCH.md requirement:
 *   k6 load test — 100 concurrent users, p95 < 500 ms
 *   Endpoints: GET /posts, GET /feed, GET /search
 *
 * Run (local):
 *   k6 run platform/loadtest/social_read.js
 *
 * Run (staging — set BASE_URL env):
 *   BASE_URL=https://agentx-platform.fly.dev k6 run platform/loadtest/social_read.js
 *
 * Optional: authenticated requests
 *   AUTH_TOKEN=<bearer-jwt> k6 run platform/loadtest/social_read.js
 *
 * Exit codes:
 *   0 — all thresholds passed
 *   99 — one or more thresholds failed
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

// ── Target ────────────────────────────────────────────────────────────────────
const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const AUTH_TOKEN = __ENV.AUTH_TOKEN || "";

// ── Custom metrics ────────────────────────────────────────────────────────────
const errorRate = new Rate("errors");
const postsLatency  = new Trend("latency_posts",  true);
const feedLatency   = new Trend("latency_feed",   true);
const searchLatency = new Trend("latency_search", true);

// ── Scenario ──────────────────────────────────────────────────────────────────
// Ramp to 100 VUs, hold for 2 min, ramp down.
export const options = {
  stages: [
    { duration: "30s", target: 100 },   // ramp-up
    { duration: "2m",  target: 100 },   // steady state
    { duration: "15s", target: 0   },   // ramp-down
  ],
  thresholds: {
    // SOCIAL_LAUNCH.md SLA: p95 < 500 ms across all three endpoints
    "http_req_duration":  ["p(95)<500"],
    "latency_posts":      ["p(95)<500"],
    "latency_feed":       ["p(95)<500"],
    "latency_search":     ["p(95)<500"],
    // Error rate must stay below 1 %
    "errors":             ["rate<0.01"],
    // HTTP errors (4xx/5xx) below 1 %
    "http_req_failed":    ["rate<0.01"],
  },
};

// ── Request helpers ───────────────────────────────────────────────────────────
function headers() {
  const h = { "Accept": "application/json" };
  if (AUTH_TOKEN) h["Authorization"] = `Bearer ${AUTH_TOKEN}`;
  return h;
}

function get(path) {
  return http.get(`${BASE_URL}${path}`, { headers: headers(), timeout: "10s" });
}

// ── Search queries to rotate through ─────────────────────────────────────────
const SEARCH_TERMS = ["agent", "task", "python", "ai", "offer", "k8s"];

// ── Virtual user entrypoint ───────────────────────────────────────────────────
export default function () {
  const roll = Math.random();

  if (roll < 0.40) {
    // 40 % — GET /posts (paginated feed, most common read)
    const r = get("/posts?limit=20");
    postsLatency.add(r.timings.duration);
    const ok = check(r, {
      "posts: status 200":     (res) => res.status === 200,
      "posts: body is json":   (res) => res.headers["Content-Type"]
                                          ?.includes("application/json"),
    });
    errorRate.add(!ok);

  } else if (roll < 0.70) {
    // 30 % — GET /feed/global
    const r = get("/feed/global?limit=20");
    feedLatency.add(r.timings.duration);
    const ok = check(r, {
      "feed: status 200 or 404": (res) => res.status === 200 || res.status === 404,
      "feed: body is json":      (res) => res.headers["Content-Type"]
                                           ?.includes("application/json"),
    });
    errorRate.add(!ok);

  } else {
    // 30 % — GET /search?q=<term>
    const q = SEARCH_TERMS[Math.floor(Math.random() * SEARCH_TERMS.length)];
    const r = get(`/search?q=${q}&type=all&limit=10`);
    searchLatency.add(r.timings.duration);
    const ok = check(r, {
      "search: status 200": (res) => res.status === 200,
      "search: body is json": (res) => res.headers["Content-Type"]
                                         ?.includes("application/json"),
    });
    errorRate.add(!ok);
  }

  // Brief think-time to mimic realistic pacing (100 ms avg)
  sleep(Math.random() * 0.2);
}

// ── Summary hook ─────────────────────────────────────────────────────────────
export function handleSummary(data) {
  const p95 = (metric) =>
    data.metrics[metric]?.values["p(95)"]?.toFixed(1) ?? "n/a";
  const rps  = data.metrics["http_reqs"]?.values["rate"]?.toFixed(1) ?? "n/a";
  const errs = (
    (data.metrics["errors"]?.values["rate"] ?? 0) * 100
  ).toFixed(2);

  console.log("\n──────────────────────────────────────────");
  console.log(" AgentX Social Read Load Test — Summary");
  console.log("──────────────────────────────────────────");
  console.log(` Target:          ${BASE_URL}`);
  console.log(` VUs peak:        100`);
  console.log(` Requests/s:      ${rps}`);
  console.log(` Error rate:      ${errs}%`);
  console.log(` p95 /posts:      ${p95("latency_posts")} ms`);
  console.log(` p95 /feed:       ${p95("latency_feed")} ms`);
  console.log(` p95 /search:     ${p95("latency_search")} ms`);
  console.log(` p95 overall:     ${p95("http_req_duration")} ms`);
  const pass = Object.values(data.metrics).every(
    (m) => !m.thresholds || Object.values(m.thresholds).every((t) => !t.ok === false),
  );
  console.log(` SLA (<500ms p95): ${pass ? "✅  PASS" : "❌  FAIL"}`);
  console.log("──────────────────────────────────────────\n");

  return {
    "loadtest/social_read_results.json": JSON.stringify(data, null, 2),
    stdout: "",
  };
}
