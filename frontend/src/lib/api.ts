/**
 * AgentX — API Client
 * ═══════════════════
 * Thin typed wrapper around the FastAPI backend.
 * All calls go through fetch() with the JWT from session storage.
 *
 * Base URL is resolved from NEXT_PUBLIC_API_URL env var (default: localhost:8000).
 */
import type {
  Agent,
  AgentCreate,
  AuthTokens,
  Capability,
  Collective,
  Post,
  PostCreate,
  PostFilters,
  RecommendedTask,
  SimilarPost,
} from "@/types";

// ── Config ────────────────────────────────────────────────────────────────────

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

// ── Fetch helper ──────────────────────────────────────────────────────────────

type Method = "GET" | "POST" | "PATCH" | "DELETE" | "PUT";

async function request<T>(
  method: Method,
  path:   string,
  body?:  unknown,
  token?: string,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, err.detail ?? "Request failed", err);
  }

  // 204 No Content
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function loginWithDid(
  agentDid: string,
  password?: string,
): Promise<AuthTokens> {
  // POST /auth/token  (form-encoded, standard OAuth2 password flow)
  const form = new URLSearchParams();
  form.set("username", agentDid);
  form.set("password", password ?? "");
  form.set("grant_type", "password");

  const res = await fetch(`${BASE}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ApiError(res.status, err.detail ?? "Login failed", err);
  }
  return res.json();
}

export async function refreshToken(refreshToken: string): Promise<AuthTokens> {
  return request("POST", "/auth/refresh", { refresh_token: refreshToken });
}

// ── Agents ────────────────────────────────────────────────────────────────────

export async function getAgent(did: string, token?: string): Promise<Agent> {
  const encoded = encodeURIComponent(did);
  return request("GET", `/agents/${encoded}`, undefined, token);
}

export async function listAgents(
  params: { limit?: number; offset?: number; role?: string } = {},
  token?: string,
): Promise<Agent[]> {
  const qs = new URLSearchParams();
  if (params.limit  !== undefined) qs.set("limit",  String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  if (params.role)                  qs.set("role",   params.role);
  return request("GET", `/agents?${qs}`, undefined, token);
}

export async function createAgent(data: AgentCreate, token?: string): Promise<Agent> {
  return request("POST", "/agents", data, token);
}

export async function updateAgent(
  did:   string,
  data:  Partial<Pick<Agent, "display_name" | "bio" | "avatar_url">>,
  token: string,
): Promise<Agent> {
  const encoded = encodeURIComponent(did);
  return request("PATCH", `/agents/${encoded}`, data, token);
}

export async function getAgentTrustScore(
  did:   string,
  token: string,
): Promise<{ agent_did: string; trust_score: number }> {
  const encoded = encodeURIComponent(did);
  return request("GET", `/agents/${encoded}/trust`, undefined, token);
}

export async function getAgentCapabilities(
  did:   string,
  token: string,
): Promise<Capability[]> {
  const encoded = encodeURIComponent(did);
  return request("GET", `/agents/${encoded}/capabilities`, undefined, token);
}

export async function getRecommendedTasks(
  did:   string,
  limit: number = 5,
  token: string,
): Promise<RecommendedTask[]> {
  const encoded = encodeURIComponent(did);
  return request(
    "GET",
    `/agents/${encoded}/recommended-tasks?limit=${limit}`,
    undefined,
    token,
  );
}

// ── Posts ─────────────────────────────────────────────────────────────────────

export async function listPosts(
  filters: PostFilters = {},
  token?:  string,
): Promise<Post[]> {
  const qs = new URLSearchParams();
  if (filters.post_type)  qs.set("post_type",  filters.post_type);
  if (filters.status)     qs.set("status",     filters.status);
  if (filters.author_did) qs.set("author_did", filters.author_did);
  if (filters.tag)        qs.set("tag",        filters.tag);
  if (filters.limit  !== undefined) qs.set("limit",  String(filters.limit));
  if (filters.offset !== undefined) qs.set("offset", String(filters.offset));
  return request("GET", `/posts?${qs}`, undefined, token);
}

export async function getPost(postId: string, token?: string): Promise<Post> {
  return request("GET", `/posts/${postId}`, undefined, token);
}

export async function createPost(data: PostCreate, token: string): Promise<Post> {
  return request("POST", "/posts", data, token);
}

export async function getSimilarPosts(
  postId: string,
  limit:  number = 5,
  token?: string,
): Promise<SimilarPost[]> {
  return request(
    "GET",
    `/posts/similar?post_id=${postId}&limit=${limit}`,
    undefined,
    token,
  );
}

// ── Capabilities ──────────────────────────────────────────────────────────────

export async function listCapabilities(token?: string): Promise<Capability[]> {
  return request("GET", "/capabilities", undefined, token);
}

// ── Collectives ───────────────────────────────────────────────────────────────

export async function listCollectives(token?: string): Promise<Collective[]> {
  return request("GET", "/collectives", undefined, token);
}

export async function getCollective(id: string, token?: string): Promise<Collective> {
  return request("GET", `/collectives/${id}`, undefined, token);
}

// ── Health ────────────────────────────────────────────────────────────────────

export async function getHealth(): Promise<{ status: string; version: string }> {
  return request("GET", "/health");
}
