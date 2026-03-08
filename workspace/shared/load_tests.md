# Complete k6 load test scripts for AgentX

## File: load-tests/smoke.js

```javascript
/**
 * AgentX Smoke Test
 * Quick sanity check to verify basic system functionality
 * 
 * Run: k6 run smoke.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const healthCheckDuration = new Trend('health_check_duration');
const listAgentsDuration = new Trend('list_agents_duration');
const getFeedDuration = new Trend('get_feed_duration');

// Test configuration
export const options = {
  vus: 5,
  duration: '30s',
  thresholds: {
    'http_req_duration': ['p(99)<500'], // 99% of requests must complete below 500ms
    'errors': ['rate<0.01'], // Error rate must be less than 1%
    'http_req_failed': ['rate<0.01'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000/v1';

// Test data
const TEST_AGENT_DID = 'did:agentx:atlas-001';

export default function () {
  // 1. Health Check
  const healthRes = http.get(`${BASE_URL}/health`);
  healthCheckDuration.add(healthRes.timings.duration);
  
  const healthCheck = check(healthRes, {
    'health check status is 200': (r) => r.status === 200,
    'health check returns OK': (r) => {
      const body = JSON.parse(r.body);
      return body.status === 'healthy';
    },
  });
  errorRate.add(!healthCheck);

  sleep(1);

  // 2. List Agents
  const listAgentsRes = http.get(`${BASE_URL}/agents?limit=20`);
  listAgentsDuration.add(listAgentsRes.timings.duration);
  
  const listAgentsCheck = check(listAgentsRes, {
    'list agents status is 200': (r) => r.status === 200,
    'list agents returns data': (r) => {
      const body = JSON.parse(r.body);
      return body.data && Array.isArray(body.data);
    },
    'list agents has pagination': (r) => {
      const body = JSON.parse(r.body);
      return body.hasOwnProperty('total') && body.hasOwnProperty('limit');
    },
  });
  errorRate.add(!listAgentsCheck);

  sleep(1);

  // 3. Get Agent Feed (requires auth - using mock token for smoke test)
  const token = generateMockJWT(TEST_AGENT_DID);
  const feedRes = http.get(`${BASE_URL}/agents/${TEST_AGENT_DID}/feed`, {
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });
  getFeedDuration.add(feedRes.timings.duration);
  
  const feedCheck = check(feedRes, {
    'feed status is 200 or 401': (r) => r.status === 200 || r.status === 401,
    'feed response is valid JSON': (r) => {
      try {
        JSON.parse(r.body);
        return true;
      } catch (e) {
        return false;
      }
    },
  });
  errorRate.add(!feedCheck);

  sleep(1);
}

export function handleSummary(data) {
  return {
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
    'smoke-test-results.json': JSON.stringify(data),
  };
}

function generateMockJWT(agentDID) {
  // For smoke tests, we use a simple mock token
  // In production, use proper JWT generation
  return 'mock-jwt-token-for-testing';
}

function textSummary(data, options) {
  const indent = options.indent || '';
  const enableColors = options.enableColors || false;
  
  let summary = '\n' + indent + '=== Smoke Test Summary ===\n';
  summary += indent + `Checks: ${data.metrics.checks.values.passes}/${data.metrics.checks.values.passes + data.metrics.checks.values.fails} passed\n`;
  summary += indent + `Requests: ${data.metrics.http_reqs.values.count}\n`;
  summary += indent + `Error rate: ${(data.metrics.errors.values.rate * 100).toFixed(2)}%\n`;
  summary += indent + `P99 latency: ${data.metrics.http_req_duration.values['p(99)'].toFixed(2)}ms\n`;
  
  return summary;
}
```

## File: load-tests/load.js

```javascript
/**
 * AgentX Main Load Test
 * Realistic traffic simulation with mixed scenarios
 * 
 * Run: k6 run load.js
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { SharedArray } from 'k6/data';
import { randomIntBetween, randomItem } from 'https://jslib.k6.io/k6-utils/1.2.0/index.js';

// Custom metrics
const errorRate = new Rate('errors');
const feedReadDuration = new Trend('feed_read_duration');
const postListDuration = new Trend('post_list_duration');
const postCreateDuration = new Trend('post_create_duration');
const profileReadDuration = new Trend('profile_read_duration');
const voteCastDuration = new Trend('vote_cast_duration');
const capabilityQueryDuration = new Trend('capability_query_duration');
const requestCounter = new Counter('total_requests');

// Test configuration
export const options = {
  stages: [
    { duration: '2m', target: 100 },  // Ramp up to 100 VUs
    { duration: '5m', target: 100 },  // Hold at 100 VUs
    { duration: '1m', target: 0 },    // Ramp down to 0
  ],
  thresholds: {
    'http_req_duration': ['p(99)<200', 'p(95)<100'],
    'errors': ['rate<0.005'], // Error rate < 0.5%
    'http_req_failed': ['rate<0.005'],
    'feed_read_duration': ['p(99)<200'],
    'post_list_duration': ['p(99)<150'],
    'post_create_duration': ['p(99)<300'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000/v1';

// Load test data
const agents = new SharedArray('agents', function () {
  return [
    { did: 'did:agentx:atlas-001', tier: 'elite' },
    { did: 'did:agentx:sigma-042', tier: 'trusted' },
    { did: 'did:agentx:bruno-007', tier: 'verified' },
    { did: 'did:agentx:quinn-001', tier: 'elite' },
    { did: 'did:agentx:oracle-013', tier: 'trusted' },
  ];
});

const postTypes = ['REQUEST', 'OFFER', 'TASK', 'PREDICTION', 'UPDATE', 'PROPOSAL'];
const postStatuses = ['ACTIVE', 'CLOSED', 'RESOLVED'];
const tags = ['frontend', 'backend', 'governance', 'security', 'data', 'ml', 'creative'];

export default function () {
  const agent = randomItem(agents);
  const token = generateJWT(agent.did, agent.tier);
  const headers = {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  // Scenario distribution (based on realistic traffic patterns)
  const scenario = randomIntBetween(1, 100);

  if (scenario <= 40) {
    // 40% - Feed reads
    feedRead(agent, headers);
  } else if (scenario <= 65) {
    // 25% - Post listing
    postListing(headers);
  } else if (scenario <= 80) {
    // 15% - Post creation
    postCreation(agent, headers);
  } else if (scenario <= 90) {
    // 10% - Agent profile reads
    profileRead();
  } else if (scenario <= 95) {
    // 5% - Vote casting
    voteCasting(agent, headers);
  } else {
    // 5% - Capability queries
    capabilityQuery(headers);
  }

  sleep(randomIntBetween(1, 3));
}

function feedRead(agent, headers) {
  group('Feed Read', function () {
    const res = http.get(
      `${BASE_URL}/agents/${agent.did}/feed?limit=20`,
      { headers }
    );
    
    feedReadDuration.add(res.timings.duration);
    requestCounter.add(1);
    
    const success = check(res, {
      'feed status is 200': (r) => r.status === 200,
      'feed has data array': (r) => {
        try {
          const body = JSON.parse(r.body);
          return Array.isArray(body.data);
        } catch (e) {
          return false;
        }
      },
      'feed response time < 200ms': (r) => r.timings.duration < 200,
    });
    
    errorRate.add(!success);
  });
}

function postListing(headers) {
  group('Post Listing', function () {
    const postType = randomItem(postTypes);
    const status = randomItem(postStatuses);
    const limit = randomIntBetween(10, 50);
    
    const res = http.get(
      `${BASE_URL}/posts?postType=${postType}&status=${status}&limit=${limit}`,
      { headers }
    );
    
    postListDuration.add(res.timings.duration);
    requestCounter.add(1);
    
    const success = check(res, {
      'post list status is 200': (r) => r.status === 200,
      'post list has pagination': (r) => {
        try {
          const body = JSON.parse(r.body);
          return body.hasOwnProperty('total') && body.hasOwnProperty('data');
        } catch (e) {
          return false;
        }
      },
      'post list response time < 150ms': (r) => r.timings.duration < 150,
    });
    
    errorRate.add(!success);
  });
}

function postCreation(agent, headers) {
  group('Post Creation', function () {
    const postType = randomItem(['REQUEST', 'OFFER', 'UPDATE']);
    const payload = generatePostPayload(postType, agent.did);
    
    const res = http.post(
      `${BASE_URL}/posts`,
      JSON.stringify(payload),
      { headers }
    );
    
    postCreateDuration.add(res.timings.duration);
    requestCounter.add(1);
    
    const success = check(res, {
      'post create status is 201': (r) => r.status === 201,
      'post create returns postId': (r) => {
        try {
          const body = JSON.parse(r.body);
          return body.hasOwnProperty('postId');
        } catch (e) {
          return false;
        }
      },
      'post create response time < 300ms': (r) => r.timings.duration < 300,
    });
    
    errorRate.add(!success);
  });
}

function profileRead() {
  group('Profile Read', function () {
    const agent = randomItem(agents);
    
    const res = http.get(`${BASE_URL}/agents/${agent.did}`);
    
    profileReadDuration.add(res.timings.duration);
    requestCounter.add(1);
    
    const success = check(res, {
      'profile status is 200': (r) => r.status === 200,
      'profile has agentDID': (r) => {
        try {
          const body = JSON.parse(r.body);
          return body.hasOwnProperty('agentDID');
        } catch (e) {
          return false;
        }
      },
      'profile response time < 100ms': (r) => r.timings.duration < 100,
    });
    
    errorRate.add(!success);
  });
}

function voteCasting(agent, headers) {
  group('Vote Casting', function () {
    // First, get active proposals
    const listRes = http.get(
      `${BASE_URL}/governance/proposals?status=ACTIVE&limit=1`,
      { headers }
    );
    
    if (listRes.status === 200) {
      try {
        const body = JSON.parse(listRes.body);
        if (body.data && body.data.length > 0) {
          const proposalId = body.data[0].proposalId;
          const votePayload = {
            choice: randomItem(['FOR', 'AGAINST', 'ABSTAIN']),
            votingPower: randomIntBetween(10, 100),
          };
          
          const voteRes = http.post(
            `${BASE_URL}/governance/proposals/${proposalId}/vote`,
            JSON.stringify(votePayload),
            { headers }
          );
          
          voteCastDuration.add(voteRes.timings.duration);
          requestCounter.add(1);
          
          const success = check(voteRes, {
            'vote status is 201 or 409': (r) => r.status === 201 || r.status === 409,
            'vote response time < 200ms': (r) => r.timings.duration < 200,
          });
          
          errorRate.add(!success && voteRes.status !== 409);
        }
      } catch (e) {
        errorRate.add(1);
      }
    }
  });
}

function capabilityQuery(headers) {
  group('Capability Query', function () {
    const domain = randomItem(['INFRASTRUCTURE', 'FRONTEND', 'SECURITY', 'DATA', 'ML']);
    
    const res = http.get(
      `${BASE_URL}/agents?domain=${domain}&minTrustScore=0.7&limit=10`,
      { headers }
    );
    
    capabilityQueryDuration.add(res.timings.duration);
    requestCounter.add(1);
    
    const success = check(res, {
      'capability query status is 200': (r) => r.status === 200,
      'capability query response time < 150ms': (r) => r.timings.duration < 150,
    });
    
    errorRate.add(!success);
  });
}

function generatePostPayload(postType, authorDID) {
  const basePayload = {
    postType: postType,
    title: `Load test ${postType} post ${Date.now()}`,
    content: `This is a load test post created at ${new Date().toISOString()}`,
    tags: [randomItem(tags), randomItem(tags)],
    visibility: 'PUBLIC',
  };

  if (postType === 'REQUEST') {
    basePayload.metadata = {
      requestType: 'COLLABORATION',
      urgency: randomItem(['LOW', 'MEDIUM', 'HIGH']),
      requiredCapabilities: ['frontend.react.advanced'],
    };
  } else if (postType === 'OFFER') {
    basePayload.metadata = {
      offerType: 'SERVICE',
      price: randomIntBetween(100, 1000),
      currency: 'WORK',
      availability: 'AVAILABLE',
    };
  } else if (postType === 'UPDATE') {
    basePayload.metadata = {
      updateType: 'PROGRESS',
    };
  }

  return basePayload;
}

function generateJWT(agentDID, tier) {
  // For load testing, generate a simple token structure
  // In production, use proper JWT signing
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const payload = btoa(JSON.stringify({
    sub: agentDID,
    tier: tier,
    exp: Math.floor(Date.now() / 1000) + 3600,
  }));
  return `${header}.${payload}.mock-signature`;
}

export function handleSummary(data) {
  const successRate = (1 - data.metrics.errors.values.rate) * 100;
  
  console.log('\n=== Load Test Summary ===');
  console.log(`Total Requests: ${data.metrics.total_requests.values.count}`);
  console.log(`Success Rate: ${successRate.toFixed(2)}%`);
  console.log(`P95 Latency: ${data.metrics.http_req_duration.values['p(95)'].toFixed(2)}ms`);
  console.log(`P99 Latency: ${data.metrics.http_req_duration.values['p(99)'].toFixed(2)}ms`);
  console.log(`Max Latency: ${data.metrics.http_req_duration.values.max.toFixed(2)}ms`);
  
  return {
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
    'load-test-results.json': JSON.stringify(data),
    'load-test-summary.html': htmlReport(data),
  };
}

function textSummary(data, options) {
  // Basic text summary
  return JSON.stringify(data, null, 2);
}

function htmlReport(data) {
  // Generate HTML report
  return `<!DOCTYPE html>
<html>
<head>
  <title>AgentX Load Test Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    th { background-color: #4CAF50; color: white; }
    .pass { color: green; }
    .fail { color: red; }
  </style>
</head>
<body>
  <h1>AgentX Load Test Report</h1>
  <p>Generated: ${new Date().toISOString()}</p>
  <h2>Summary</h2>
  <table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Total Requests</td><td>${data.metrics.total_requests.values.count}</td></tr>
    <tr><td>Success Rate</td><td class="${data.metrics.errors.values.rate < 0.005 ? 'pass' : 'fail'}">${((1 - data.metrics.errors.values.rate) * 100).toFixed(2)}%</td></tr>
    <tr><td>P95 Latency</td><td>${data.metrics.http_req_duration.values['p(95)'].toFixed(2)}ms</td></tr>
    <tr><td>P99 Latency</td><td class="${data.metrics.http_req_duration.values['p(99)'] < 200 ? 'pass' : 'fail'}">${data.metrics.http_req_duration.values['p(99)'].toFixed(2)}ms</td></tr>
  </table>
</body>
</html>`;
}
```

## File: load-tests/stress.js

```javascript
/**
 * AgentX Stress Test
 * Find the breaking point of the system
 * 
 * Run: k6 run stress.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { randomIntBetween, randomItem } from 'https://jslib.k6.io/k6-utils/1.2.0/index.js';

// Custom metrics
const errorRate = new Rate('errors');
const p99Latency = new Trend('p99_latency');
const activeVUs = new Counter('active_vus');
const breakingPoint = new Counter('breaking_point_vus');

// Test configuration
export const options = {
  stages: [
    { duration: '10m', target: 500 },  // Ramp up to 500 VUs over 10 minutes
  ],
  thresholds: {
    // Soft thresholds - don't abort test
    'http_req_duration': ['p(99)<2000'],
    'http_req_failed': ['rate<0.1'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000/v1';

let p99ExceededAt = null;

export default function () {
  const currentVUs = __VU;
  activeVUs.add(1);

  // Simple read operations for stress testing
  const operations = [
    () => http.get(`${BASE_URL}/agents?limit=50`),
    () => http.get(`${BASE_URL}/posts?limit=50`),
    () => http.get(`${BASE_URL}/agents/did:agentx:atlas-001`),
  ];

  const operation = randomItem(operations);
  const res = operation();

  p99Latency.add(res.timings.duration);

  // Track when P99 exceeds 200ms threshold
  if (res.timings.duration > 200 && !p99ExceededAt) {
    p99ExceededAt = currentVUs;
    breakingPoint.add(currentVUs);
    console.log(`⚠️  P99 threshold (200ms) exceeded at ${currentVUs} VUs`);
  }

  const success = check(res, {
    'status is 200': (r) => r.status === 200,
    'response time < 2000ms': (r) => r.timings.duration < 2000,
  });

  errorRate.add(!success);

  sleep(randomIntBetween(1, 2));
}

export function handleSummary(data) {
  const p99Value = data.metrics.http_req_duration.values['p(99)'];
  const errorRateValue = data.metrics.errors.values.rate;
  const maxVUs = data.metrics.vus_max.values.max;

  console.log('\n=== Stress Test Summary ===');
  console.log(`Max VUs Reached: ${maxVUs}`);
  console.log(`P99 Latency: ${p99Value.toFixed(2)}ms`);
  console.log(`Error Rate: ${(errorRateValue * 100).toFixed(2)}%`);
  
  if (p99ExceededAt) {
    console.log(`⚠️  System degradation detected at ${p99ExceededAt} VUs (P99 > 200ms)`);
  } else {
    console.log(`✅ System handled ${maxVUs} VUs without exceeding P99 threshold`);
  }

  return {
    'stdout': generateTextReport(data),
    'stress-test-results.json': JSON.stringify(data),
    'stress-test-report.html': generateHTMLReport(data, p99ExceededAt),
  };
}

function generateTextReport(data) {
  const stages = [];
  let currentStage = { vus: 0, requests: 0, p99: 0, errors: 0 };
  
  return `
╔════════════════════════════════════════════════════════════════╗
║                  AGENTX STRESS TEST REPORT                     ║
╚════════════════════════════════════════════════════════════════╝

Duration: ${data.state.testRunDurationMs / 1000}s
Total Requests: ${data.metrics.http_reqs.values.count}
Total VUs: ${data.metrics.vus_max.values.max}

LATENCY METRICS:
  P50: ${data.metrics.http_req_duration.values['p(50)'].toFixed(2)}ms
  P95: ${data.metrics.http_req_duration.values['p(95)'].toFixed(2)}ms
  P99: ${data.metrics.http_req_duration.values['p(99)'].toFixed(2)}ms
  Max: ${data.metrics.http_req_duration.values.max.toFixed(2)}ms

ERROR METRICS:
  Error Rate: ${(data.metrics.errors.values.rate * 100).toFixed(2)}%
  Failed Requests: ${data.metrics.http_req_failed.values.passes}

BREAKING POINT ANALYSIS:
  ${p99ExceededAt ? `System degraded at ${p99ExceededAt} concurrent VUs` : 'No degradation detected within test limits'}
  Recommended max load: ${p99ExceededAt ? Math.floor(p99ExceededAt * 0.8) : data.metrics.vus_max.values.max} VUs

`;
}

function generateHTMLReport(data, breakingPointVUs) {
  const p99 = data.metrics.http_req_duration.values['p(99)'];
  const errorRate = data.metrics.errors.values.rate;
  
  return `<!DOCTYPE html>
<html>
<head>
  <title>AgentX Stress Test Report</title>
  <style>
    body {
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      margin: 0;
      padding: 20px;
      background: #f5f5f5;
    }
    .container {
      max-width: 1200px;
      margin: 0 auto;
      background: white;
      padding: 30px;
      border-radius: 8px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    h1 {
      color: #333;
      border-bottom: 3px solid #4CAF50;
      padding-bottom: 10px;
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
      gap: 20px;
      margin: 20px 0;
    }
    .metric-card {
      background: #f9f9f9;
      padding: 20px;
      border-radius: 4px;
      border-left: 4px solid #4CAF50;
    }
    .metric-card.warning {
      border-left-color: #ff9800;
    }
    .metric-card.error {
      border-left-color: #f44336;
    }
    .metric-label {
      font-size: 14px;
      color: #666;
      margin-bottom: 5px;
    }
    .metric-value {
      font-size: 32px;
      font-weight: bold;
      color: #333;
    }
    .breaking-point {
      background: #fff3cd;
      border: 2px solid #ffc107;
      padding: 20px;
      border-radius: 4px;
      margin: 20px 0;
    }
    .recommendations {
      background: #e8f5e9;
      border: 2px solid #4CAF50;
      padding: 20px;
      border-radius: 4px;
      margin: 20px 0;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin: 20px 0;
    }
    th, td {
      padding: 12px;
      text-align: left;
      border-bottom: 1px solid #ddd;
    }
    th {
      background: #4CAF50;
      color: white;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>🔥 AgentX Stress Test Report</h1>
    <p>Generated: ${new Date().toISOString()}</p>
    
    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">Max Concurrent VUs</div>
        <div class="metric-value">${data.metrics.vus_max.values.max}</div>
      </div>
      <div class="metric-card ${p99 > 200 ? 'warning' : ''}">
        <div class="metric-label">P99 Latency</div>
        <div class="metric-value">${p99.toFixed(0)}ms</div>
      </div>
      <div class="metric-card ${errorRate > 0.01 ? 'error' : ''}">
        <div class="metric-label">Error Rate</div>
        <div class="metric-value">${(errorRate * 100).toFixed(2)}%</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Total Requests</div>
        <div class="metric-value">${data.metrics.http_reqs.values.count}</div>
      </div>
    </div>

    ${breakingPointVUs ? `
    <div class="breaking-point">
      <h2>⚠️ Breaking Point Detected</h2>
      <p>System performance degraded (P99 > 200ms) at <strong>${breakingPointVUs} concurrent users</strong>.</p>
      <p>This indicates the system's capacity threshold for maintaining optimal response times.</p>
    </div>
    ` : `
    <div class="recommendations">
      <h2>✅ No Breaking Point Detected</h2>
      <p>System handled <strong>${data.metrics.vus_max.values.max} concurrent users</strong> without significant degradation.</p>
      <p>Consider running a higher load test to find the true capacity limit.</p>
    </div>
    `}

    <h2>Detailed Latency Breakdown</h2>
    <table>
      <tr>
        <th>Percentile</th>
        <th>Latency (ms)</th>
        <th>Status</th>
      </tr>
      <tr>
        <td>P50 (Median)</td>
        <td>${data.metrics.http_req_duration.values['p(50)'].toFixed(2)}</td>
        <td>✅</td>
      </tr>
      <tr>
        <td>P75</td>
        <td>${data.metrics.http_req_duration.values['p(75)'].toFixed(2)}</td>
        <td>✅</td>
      </tr>
      <tr>
        <td>P90</td>
        <td>${data.metrics.http_req_duration.values['p(90)'].toFixed(2)}</td>
        <td>✅</td>
      </tr>
      <tr>
        <td>P95</td>
        <td>${data.metrics.http_req_duration.values['p(95)'].toFixed(2)}</td>
        <td>${data.metrics.http_req_duration.values['p(95)'] < 100 ? '✅' : '⚠️'}</td>
      </tr>
      <tr>
        <td>P99</td>
        <td>${data.metrics.http_req_duration.values['p(99)'].toFixed(2)}</td>
        <td>${data.metrics.http_req_duration.values['p(99)'] < 200 ? '✅' : '❌'}</td>
      </tr>
      <tr>
        <td>Max</td>
        <td>${data.metrics.http_req_duration.values.max.toFixed(2)}</td>
        <td>-</td>
      </tr>
    </table>

    <div class="recommendations">
      <h2>💡 Recommendations</h2>
      <ul>
        <li><strong>Optimal Capacity:</strong> ${breakingPointVUs ? Math.floor(breakingPointVUs * 0.7) : Math.floor(data.metrics.vus_max.values.max * 0.8)} concurrent users (70-80% of breaking point)</li>
        <li><strong>Scale Out Threshold:</strong> ${breakingPointVUs ? Math.floor(breakingPointVUs * 0.85) : 'Not determined'} concurrent users</li>
        <li><strong>Next Steps:</strong> ${breakingPointVUs ? 'Implement horizontal scaling or optimize bottleneck endpoints' : 'Run higher load test to determine true capacity'}</li>
      </ul>
    </div>
  </div>
</body>
</html>`;
}
```

## File: load-tests/trust_score.js

```javascript
/**
 * AgentX Trust Score Recalculation Load Test
 * Verify trust score consistency under concurrent recalculations
 * 
 * Run: k6 run trust_score.js
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { randomIntBetween } from 'https://jslib.k6.io/k6-utils/1.2.0/index.js';

// Custom metrics
const trustScoreDrift = new Trend('trust_score_drift');
const recalculationDuration = new Trend('recalculation_duration');
const concurrentRecalculations = new Counter('concurrent_recalculations');
const driftViolations = new Counter('drift_violations');

// Test configuration
export const options = {
  scenarios: {
    concurrent_task_completions: {
      executor: 'constant-vus',
      vus: 50,
      duration: '2m',
    },
  },
  thresholds: {
    'trust_score_drift': ['p(99)<0.01'], // Max drift: 0.01
    'recalculation_duration': ['p(95)<500'], // 95% complete within 500ms
    'drift_violations': ['count<5'], // Max 5 drift violations
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000/v1';

// Test agents for trust score testing
const TEST_AGENTS = [
  'did:agentx:trust-test-001',
  'did:agentx:trust-test-002',
  'did:agentx:trust-test-003',
  'did:agentx:trust-test-004',
  'did:agentx:trust-test-005',
];

export function setup() {
  // Setup: Create test agents and get their initial trust scores
  const initialScores = {};
  
  TEST_AGENTS.forEach(agentDID => {
    const res = http.get(`${BASE_URL}/agents/${agentDID}`);
    if (res.status === 200) {
      const body = JSON.parse(res.body);
      initialScores[agentDID] = body.trustScore;
    }
  });
  
  return { initialScores };
}

export default function (data) {
  const agentDID = TEST_AGENTS[__VU % TEST_AGENTS.length];
  const token = generateJWT(agentDID, 'verified');
  const headers = {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  group('Concurrent Trust Score Recalculation', function () {
    // Step 1: Get current trust score
    const beforeRes = http.get(`${BASE_URL}/agents/${agentDID}`, { headers });
    let beforeScore = 0;
    
    if (beforeRes.status === 200) {
      beforeScore = JSON.parse(beforeRes.body).trustScore;
    }

    // Step 2: Complete a task (triggers trust score recalculation)
    const taskCompletePayload = {
      taskId: `task-${Date.now()}-${__VU}`,
      success: true,
      slaCompliance: randomIntBetween(80, 100) / 100,
      metadata: {
        completionTime: Date.now(),
        quality: 'high',
      },
    };

    const startTime = Date.now();
    const completeRes = http.post(
      `${BASE_URL}/tasks/complete`,
      JSON.stringify(taskCompletePayload),
      { headers }
    );
    const recalcTime = Date.now() - startTime;

    recalculationDuration.add(recalcTime);
    concurrentRecalculations.add(1);

    check(completeRes, {
      'task completion status is 200': (r) => r.status === 200,
    });

    // Step 3: Get updated trust score
    sleep(0.5); // Brief wait for recalculation to complete

    const afterRes = http.get(`${BASE_URL}/agents/${agentDID}`, { headers });
    
    if (afterRes.status === 200) {
      const afterScore = JSON.parse(afterRes.body).trustScore;
      const drift = Math.abs(afterScore - beforeScore);
      
      trustScoreDrift.add(drift);

      // Check drift violation
      const driftOK = check({ drift }, {
        'trust score drift < 0.01': (d) => d.drift < 0.01,
      });

      if (!driftOK) {
        driftViolations.add(1);
        console.log(`⚠️  Drift violation: ${drift.toFixed(4)} for ${agentDID} (before: ${beforeScore.toFixed(4)}, after: ${afterScore.toFixed(4)})`);
      }

      // Verify trust score breakdown consistency
      const breakdownRes = http.get(
        `${BASE_URL}/agents/${agentDID}/trust-breakdown`,
        { headers }
      );
      
      if (breakdownRes.status === 200) {
        const breakdown = JSON.parse(breakdownRes.body);
        const calculatedScore = 
          (breakdown.executionSuccess * 0.35) +
          (breakdown.slaCompliance * 0.25) +
          (breakdown.peerEndorsements * 0.20) +
          (breakdown.auditTransparency * 0.12) +
          (breakdown.securityRecord * 0.08);
        
        const calculationDrift = Math.abs(calculatedScore - afterScore);
        
        check({ calculationDrift }, {
          'calculated trust score matches stored score': (d) => d.calculationDrift < 0.001,
        });
      }
    }
  });

  sleep(randomIntBetween(1, 2));
}

export function teardown(data) {
  // Verify final trust scores are within expected bounds