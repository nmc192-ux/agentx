/**
 * AgentX Frontend — API Client Tests
 * ════════════════════════════════════
 * Pure unit tests for the API client (no React, no DOM).
 * Uses Jest + global fetch mock.
 */
import { ApiError, getAgent, listPosts, getSimilarPosts, getHealth } from "@/lib/api";

// ── Mock fetch globally ────────────────────────────────────────────────────────

const mockFetch = jest.fn();
global.fetch = mockFetch;

function mockOk(body: unknown, status = 200) {
  mockFetch.mockResolvedValueOnce({
    ok:     true,
    status,
    json:   async () => body,
    text:   async () => JSON.stringify(body),
  } as Response);
}

function mockError(status: number, detail = "Not found") {
  mockFetch.mockResolvedValueOnce({
    ok:     false,
    status,
    json:   async () => ({ detail }),
    text:   async () => JSON.stringify({ detail }),
  } as Response);
}

beforeEach(() => {
  mockFetch.mockClear();
});

// ── getHealth ─────────────────────────────────────────────────────────────────

describe("getHealth", () => {
  it("returns health object on success", async () => {
    mockOk({ status: "ok", version: "0.5.0" });
    const result = await getHealth();
    expect(result.status).toBe("ok");
    expect(result.version).toBe("0.5.0");
  });

  it("calls GET /health", async () => {
    mockOk({ status: "ok", version: "0.5.0" });
    await getHealth();
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/health"),
      expect.objectContaining({ method: "GET" }),
    );
  });
});

// ── getAgent ──────────────────────────────────────────────────────────────────

describe("getAgent", () => {
  const fakeAgent = {
    agent_did:       "did:agentx:nova-001",
    display_name:    "Nova",
    governance_role: "MEMBER",
    tier:            "STANDARD",
    status:          "ACTIVE",
    trust_score:     0.75,
    created_at:      "2024-01-01T00:00:00Z",
    updated_at:      "2024-01-01T00:00:00Z",
  };

  it("returns agent on success", async () => {
    mockOk(fakeAgent);
    const agent = await getAgent("did:agentx:nova-001", "token123");
    expect(agent.agent_did).toBe("did:agentx:nova-001");
    expect(agent.trust_score).toBe(0.75);
  });

  it("throws ApiError on 404", async () => {
    mockError(404, "Agent not found");
    await expect(getAgent("did:agentx:ghost-999", "token123")).rejects.toThrow(ApiError);
  });

  it("includes Authorization header when token provided", async () => {
    mockOk(fakeAgent);
    await getAgent("did:agentx:nova-001", "my-jwt");
    const [, init] = mockFetch.mock.calls[0];
    expect((init as RequestInit).headers).toEqual(
      expect.objectContaining({ Authorization: "Bearer my-jwt" }),
    );
  });

  it("URL-encodes the DID", async () => {
    mockOk(fakeAgent);
    await getAgent("did:agentx:nova-001", "tok");
    const [url] = mockFetch.mock.calls[0];
    expect(url).toContain(encodeURIComponent("did:agentx:nova-001"));
  });
});

// ── listPosts ─────────────────────────────────────────────────────────────────

describe("listPosts", () => {
  const fakePosts = [
    {
      post_id:    "pid-1",
      author_did: "did:agentx:atlas-001",
      post_type:  "TASK",
      title:      "Deploy service",
      content:    "We need to deploy…",
      status:     "ACTIVE",
      visibility: "PUBLIC",
      tags:       ["infrastructure"],
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
    },
  ];

  it("returns posts array", async () => {
    mockOk(fakePosts);
    const posts = await listPosts();
    expect(Array.isArray(posts)).toBe(true);
    expect(posts[0].post_type).toBe("TASK");
  });

  it("passes post_type filter as query param", async () => {
    mockOk(fakePosts);
    await listPosts({ post_type: "OFFER" });
    const [url] = mockFetch.mock.calls[0];
    expect(url).toContain("post_type=OFFER");
  });

  it("passes limit and offset", async () => {
    mockOk(fakePosts);
    await listPosts({ limit: 10, offset: 20 });
    const [url] = mockFetch.mock.calls[0];
    expect(url).toContain("limit=10");
    expect(url).toContain("offset=20");
  });
});

// ── getSimilarPosts ───────────────────────────────────────────────────────────

describe("getSimilarPosts", () => {
  it("returns similar posts with similarity score", async () => {
    const fakeSimilar = [
      { post_id: "pid-2", title: "Similar task", content: "…", similarity: 0.92 },
    ];
    mockOk(fakeSimilar);
    const results = await getSimilarPosts("pid-1", 5);
    expect(results[0].similarity).toBe(0.92);
  });

  it("passes post_id and limit to query string", async () => {
    mockOk([]);
    await getSimilarPosts("abc-123", 3);
    const [url] = mockFetch.mock.calls[0];
    expect(url).toContain("post_id=abc-123");
    expect(url).toContain("limit=3");
  });
});

// ── ApiError ──────────────────────────────────────────────────────────────────

describe("ApiError", () => {
  it("has correct status and message", () => {
    const err = new ApiError(404, "Not found");
    expect(err.status).toBe(404);
    expect(err.message).toBe("Not found");
    expect(err.name).toBe("ApiError");
  });

  it("is instance of Error", () => {
    expect(new ApiError(500, "Oops")).toBeInstanceOf(Error);
  });
});
