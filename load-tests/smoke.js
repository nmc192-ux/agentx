/**
 * AgentX — Smoke Test
 * ════════════════════════════════════════════════════════════════════════════
 * Quick sanity check — 5 VUs × 30 s.
 * Verifies basic system health before promoting to staging / production.
 *
 * Run:
 *   k6 run smoke.js
 *   k6 run smoke.js -e BASE_URL=https://api.agentx.io/v1
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

// ── Custom metrics ────────────────────────────────────────────────────────────
const errorRate            = new Rate("errors");
const healthCheckDuration  = new Trend("health_check_duration");
const listAgentsDuration   = new Trend("list_agents_duration");
const getFeedDuration      = new Trend("get_feed_duration");

// ── Test configuration ────────────────────────────────────────────────────────
export const options = {
  vus:      5,
  duration: "30s",
  thresholds: {
    "http_req_duration":  ["p(99)<500"],   // 99th pct < 500 ms
    "errors":             ["rate<0.01"],   // error rate < 1%
    "http_req_failed":    ["rate<0.01"],
    "health_check_duration": ["p(99)<200"],
    "list_agents_duration":  ["p(99)<300"],
    "get_feed_duration":     ["p(99)<400"],
  },
};

const BASE_URL        = __ENV.BASE_URL || "http://localhost:8000/v1";
const TEST_AGENT_DID  = __ENV.TEST_DID || "did:agentx:atlas-001";

// ── Helpers ───────────────────────────────────────────────────────────────────
function authHeaders(agentDID) {
  // Smoke tests use a well-known dev token (API validates in test mode)
  // Override with k6 -e AUTH_TOKEN=<real-jwt> for staging
  const token = __ENV.AUTH_TOKEN || "smoke-test-dev-token";
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

// ── Main iteration ────────────────────────────────────────────────────────────
export default function () {
  const headers = authHeaders(TEST_AGENT_DID);

  // ── 1. Health check ──────────────────────────────────────────────────────
  const healthRes = http.get(`${BASE_URL.replace("/v1", "")}/health`, {
    tags: { endpoint: "health" },
  });
  healthCheckDuration.add(healthRes.timings.duration);

  const healthOK = check(healthRes, {
    "health: status 200":         (r) => r.status === 200,
    "health: status field is ok": (r) => {
      try {
        return JSON.parse(r.body).status === "ok";
      } catch (_) {
        return false;
      }
    },
  });
  errorRate.add(!healthOK);

  sleep(1);

  // ── 2. List agents ───────────────────────────────────────────────────────
  const agentsRes = http.get(`${BASE_URL}/agents?limit=20`, {
    tags: { endpoint: "list_agents" },
  });
  listAgentsDuration.add(agentsRes.timings.duration);

  const agentsOK = check(agentsRes, {
    "agents: status 200":     (r) => r.status === 200,
    "agents: is array":       (r) => {
      try {
        const b = JSON.parse(r.body);
        return Array.isArray(b) || Array.isArray(b.data);
      } catch (_) {
        return false;
      }
    },
  });
  errorRate.add(!agentsOK);

  sleep(1);

  // ── 3. Get personalised feed ─────────────────────────────────────────────
  const encodedDID = encodeURIComponent(TEST_AGENT_DID);
  const feedRes    = http.get(
    `${BASE_URL}/agents/${encodedDID}/feed?limit=10`,
    { headers, tags: { endpoint: "feed" } },
  );
  getFeedDuration.add(feedRes.timings.duration);

  const feedOK = check(feedRes, {
    "feed: status 200 or 401": (r) => r.status === 200 || r.status === 401,
    "feed: valid JSON":        (r) => {
      try {
        JSON.parse(r.body);
        return true;
      } catch (_) {
        return false;
      }
    },
  });
  errorRate.add(!feedOK);

  sleep(1);
}

// ── Summary ───────────────────────────────────────────────────────────────────
export function handleSummary(data) {
  const passed  = data.metrics.checks.values.passes;
  const failed  = data.metrics.checks.values.fails;
  const total   = passed + failed;
  const errPct  = (data.metrics.errors.values.rate * 100).toFixed(2);
  const p99     = data.metrics.http_req_duration.values["p(99)"].toFixed(1);

  const lines = [
    "",
    "╔══════════════════════════════════╗",
    "║   AgentX Smoke Test Summary      ║",
    "╚══════════════════════════════════╝",
    `  Checks:     ${passed}/${total} passed`,
    `  Error rate: ${errPct}%`,
    `  P99 latency: ${p99} ms`,
    "",
  ];
  console.log(lines.join("\n"));

  return {
    stdout: lines.join("\n"),
    "results/smoke-results.json": JSON.stringify(data, null, 2),
  };
}
