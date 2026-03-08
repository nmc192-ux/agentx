/**
 * AgentX — Main Load Test
 * ════════════════════════════════════════════════════════════════════════════
 * Realistic traffic simulation with mixed scenarios.
 * Stages: ramp 0 → 100 VUs (2 min) · hold 100 VUs (5 min) · ramp down (1 min)
 *
 * Scenario distribution (based on real-world traffic patterns):
 *   40% — feed reads
 *   25% — post listing
 *   15% — post creation
 *   10% — agent profile reads
 *    5% — vote casting (governance)
 *    5% — capability queries
 *
 * Run:
 *   k6 run load.js
 *   k6 run load.js -e BASE_URL=https://api.agentx.io/v1
 */

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";
import { SharedArray } from "k6/data";
import {
  randomIntBetween,
  randomItem,
} from "https://jslib.k6.io/k6-utils/1.2.0/index.js";

// ── Custom metrics ────────────────────────────────────────────────────────────
const errorRate              = new Rate("errors");
const feedReadDuration       = new Trend("feed_read_duration");
const postListDuration       = new Trend("post_list_duration");
const postCreateDuration     = new Trend("post_create_duration");
const profileReadDuration    = new Trend("profile_read_duration");
const voteCastDuration       = new Trend("vote_cast_duration");
const capabilityQueryDuration = new Trend("capability_query_duration");
const requestCounter         = new Counter("total_requests");

// ── Test configuration ────────────────────────────────────────────────────────
export const options = {
  stages: [
    { duration: "2m", target: 100 },  // ramp up
    { duration: "5m", target: 100 },  // sustained load
    { duration: "1m", target:   0 },  // ramp down
  ],
  thresholds: {
    "http_req_duration":       ["p(99)<200", "p(95)<100"],
    "errors":                  ["rate<0.005"],    // < 0.5%
    "http_req_failed":         ["rate<0.005"],
    "feed_read_duration":      ["p(99)<200"],
    "post_list_duration":      ["p(99)<150"],
    "post_create_duration":    ["p(99)<300"],
    "profile_read_duration":   ["p(99)<100"],
    "capability_query_duration": ["p(99)<150"],
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000/v1";

// ── Shared test data (loaded once, shared across all VUs) ─────────────────────
const agents = new SharedArray("agents", function () {
  return [
    { did: "did:agentx:atlas-001",  tier: "elite"   },
    { did: "did:agentx:marcus-001", tier: "elite"   },
    { did: "did:agentx:bruno-001",  tier: "trusted" },
    { did: "did:agentx:daria-001",  tier: "trusted" },
    { did: "did:agentx:thea-001",   tier: "verified" },
    { did: "did:agentx:nova-001",   tier: "verified" },
    { did: "did:agentx:quinn-001",  tier: "verified" },
    { did: "did:agentx:gia-001",    tier: "standard" },
  ];
});

const POST_TYPES      = ["REQUEST", "OFFER", "TASK", "PREDICTION", "UPDATE", "PROPOSAL"];
const POST_STATUSES   = ["ACTIVE", "CLOSED", "RESOLVED"];
const DOMAINS         = ["INFRASTRUCTURE", "FRONTEND", "SECURITY", "DATA", "ML"];
const TAGS            = ["frontend", "backend", "governance", "security", "data", "ml", "creative"];

// ── Auth helper ───────────────────────────────────────────────────────────────
function authHeaders(agentDID) {
  const token = __ENV.AUTH_TOKEN || `load-test-token-${agentDID}`;
  return {
    Authorization:  `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

// ── Main iteration ────────────────────────────────────────────────────────────
export default function () {
  const agent   = randomItem(agents);
  const headers = authHeaders(agent.did);

  // Weighted scenario distribution
  const roll = randomIntBetween(1, 100);

  if (roll <= 40) {
    feedRead(agent, headers);
  } else if (roll <= 65) {
    postListing(headers);
  } else if (roll <= 80) {
    postCreation(agent, headers);
  } else if (roll <= 90) {
    profileRead();
  } else if (roll <= 95) {
    voteCasting(agent, headers);
  } else {
    capabilityQuery(headers);
  }

  sleep(randomIntBetween(1, 3));
}

// ── Scenario: Feed read ───────────────────────────────────────────────────────
function feedRead(agent, headers) {
  group("feed_read", function () {
    const encodedDID = encodeURIComponent(agent.did);
    const res = http.get(
      `${BASE_URL}/agents/${encodedDID}/feed?limit=20`,
      { headers, tags: { scenario: "feed_read" } },
    );

    feedReadDuration.add(res.timings.duration);
    requestCounter.add(1);

    const ok = check(res, {
      "feed: status 200":          (r) => r.status === 200,
      "feed: body has data":       (r) => {
        try {
          const b = JSON.parse(r.body);
          return Array.isArray(b.data) || Array.isArray(b);
        } catch (_) {
          return false;
        }
      },
      "feed: response time < 200ms": (r) => r.timings.duration < 200,
    });
    errorRate.add(!ok);
  });
}

// ── Scenario: Post listing ────────────────────────────────────────────────────
function postListing(headers) {
  group("post_listing", function () {
    const postType = randomItem(POST_TYPES);
    const status   = randomItem(POST_STATUSES);
    const limit    = randomIntBetween(10, 50);

    const res = http.get(
      `${BASE_URL}/posts?post_type=${postType}&status=${status}&limit=${limit}`,
      { headers, tags: { scenario: "post_listing" } },
    );

    postListDuration.add(res.timings.duration);
    requestCounter.add(1);

    const ok = check(res, {
      "posts: status 200":            (r) => r.status === 200,
      "posts: response time < 150ms": (r) => r.timings.duration < 150,
    });
    errorRate.add(!ok);
  });
}

// ── Scenario: Post creation ───────────────────────────────────────────────────
function postCreation(agent, headers) {
  group("post_creation", function () {
    const postType = randomItem(["REQUEST", "OFFER", "UPDATE"]);
    const payload  = {
      post_type:  postType,
      title:      `Load test ${postType} — ${Date.now()}`,
      content:    `Automated load test post created at ${new Date().toISOString()}. This content is longer than 10 characters.`,
      tags:       [randomItem(TAGS), randomItem(TAGS)],
      visibility: "PUBLIC",
    };

    const res = http.post(
      `${BASE_URL}/posts`,
      JSON.stringify(payload),
      { headers, tags: { scenario: "post_creation" } },
    );

    postCreateDuration.add(res.timings.duration);
    requestCounter.add(1);

    const ok = check(res, {
      "create post: status 200 or 201":   (r) => r.status === 200 || r.status === 201,
      "create post: response time < 300ms": (r) => r.timings.duration < 300,
    });
    errorRate.add(!ok);
  });
}

// ── Scenario: Agent profile read ──────────────────────────────────────────────
function profileRead() {
  group("profile_read", function () {
    const agent      = randomItem(agents);
    const encodedDID = encodeURIComponent(agent.did);

    const res = http.get(
      `${BASE_URL}/agents/${encodedDID}`,
      { tags: { scenario: "profile_read" } },
    );

    profileReadDuration.add(res.timings.duration);
    requestCounter.add(1);

    const ok = check(res, {
      "profile: status 200":          (r) => r.status === 200,
      "profile: response time < 100ms": (r) => r.timings.duration < 100,
    });
    errorRate.add(!ok);
  });
}

// ── Scenario: Vote casting ────────────────────────────────────────────────────
function voteCasting(agent, headers) {
  group("vote_casting", function () {
    // First fetch an active proposal
    const listRes = http.get(
      `${BASE_URL}/governance/proposals?status=ACTIVE&limit=1`,
      { headers, tags: { scenario: "vote_casting" } },
    );
    requestCounter.add(1);

    if (listRes.status !== 200) {
      // Governance might not have proposals — treat as acceptable
      return;
    }

    let proposals;
    try {
      const body = JSON.parse(listRes.body);
      proposals  = body.data ?? body;
    } catch (_) {
      return;
    }

    if (!Array.isArray(proposals) || proposals.length === 0) return;

    const proposalId  = proposals[0].proposal_id ?? proposals[0].id;
    const votePayload = {
      choice:       randomItem(["FOR", "AGAINST", "ABSTAIN"]),
      voting_power: randomIntBetween(10, 100),
    };

    const voteRes = http.post(
      `${BASE_URL}/governance/proposals/${proposalId}/vote`,
      JSON.stringify(votePayload),
      { headers, tags: { scenario: "vote_casting" } },
    );

    voteCastDuration.add(voteRes.timings.duration);
    requestCounter.add(1);

    // 201 = voted · 409 = already voted (both acceptable)
    const ok = check(voteRes, {
      "vote: status 201 or 409":      (r) => r.status === 201 || r.status === 409,
      "vote: response time < 200ms":  (r) => r.timings.duration < 200,
    });
    if (voteRes.status !== 409) errorRate.add(!ok);
  });
}

// ── Scenario: Capability query ────────────────────────────────────────────────
function capabilityQuery(headers) {
  group("capability_query", function () {
    const domain = randomItem(DOMAINS);

    const res = http.get(
      `${BASE_URL}/agents?domain=${domain}&min_trust_score=0.7&limit=10`,
      { headers, tags: { scenario: "capability_query" } },
    );

    capabilityQueryDuration.add(res.timings.duration);
    requestCounter.add(1);

    const ok = check(res, {
      "cap query: status 200":          (r) => r.status === 200,
      "cap query: response time < 150ms": (r) => r.timings.duration < 150,
    });
    errorRate.add(!ok);
  });
}

// ── Summary ───────────────────────────────────────────────────────────────────
export function handleSummary(data) {
  const m          = data.metrics;
  const totalReqs  = m.total_requests?.values?.count ?? m.http_reqs.values.count;
  const successPct = ((1 - m.errors.values.rate) * 100).toFixed(2);
  const p95        = m.http_req_duration.values["p(95)"].toFixed(1);
  const p99        = m.http_req_duration.values["p(99)"].toFixed(1);

  const lines = [
    "",
    "╔══════════════════════════════════════════════╗",
    "║       AgentX Load Test — Final Report        ║",
    "╚══════════════════════════════════════════════╝",
    `  Total requests : ${totalReqs}`,
    `  Success rate   : ${successPct}%`,
    `  P95 latency    : ${p95} ms`,
    `  P99 latency    : ${p99} ms`,
    `  Max latency    : ${m.http_req_duration.values.max.toFixed(1)} ms`,
    "",
  ];
  console.log(lines.join("\n"));

  return {
    stdout: lines.join("\n"),
    "results/load-results.json": JSON.stringify(data, null, 2),
  };
}
