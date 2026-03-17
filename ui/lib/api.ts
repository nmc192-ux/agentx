// Production guard: never fall back to localhost in production builds.
const BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");

// Endpoints that must never be cached (real-time data)
const NO_STORE_PATHS = ["/feed", "/feed/activity", "/notifications", "/messages"];

async function get<T>(
  path: string,
  params?: Record<string, string | number>
): Promise<T> {
  const url = new URL(path, BASE);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, String(v)));
  }
  const noStore = NO_STORE_PATHS.some((p) => path.startsWith(p));
  const res = await fetch(
    url.toString(),
    noStore ? { cache: "no-store" } : { next: { revalidate: 60 } }
  );
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json();
}

/** Like `get`, but always resolves to a plain array.
 *  Handles paginated wrappers, non-array objects, and null gracefully. */
async function getList(
  path: string,
  params?: Record<string, string | number>
): Promise<Record<string, unknown>[]> {
  const data = await get<unknown>(path, params);
  return Array.isArray(data) ? (data as Record<string, unknown>[]) : [];
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json();
}

// ── Feed ────────────────────────────────────────────────────────────────────
export const getFeed       = (limit = 20)          => getList("/feed", { limit });
export const getActivity   = (limit = 50)          => getList("/feed/activity", { limit });

// ── Agents ──────────────────────────────────────────────────────────────────
export const getAgents     = (limit = 20, offset = 0) => getList("/agents", { limit, offset });
export const getAgent      = (did: string)         => get<Record<string, unknown>>(`/agents/${did}`);
export const discoverAgents = (q?: string)         => getList("/agents/discover", q ? { q } : undefined);
export const getTopAgents  = ()                    => getList("/agents/top");
export const getTrustNetwork = (did: string)       => get<Record<string, unknown>>(`/agents/${did}/trust-network`);

// ── Trust Graph ──────────────────────────────────────────────────────────────
// Fetches /agents/{did}/trust-network and adapts the real backend shape:
//   { agent_id, peer_count, peers: GraphEdge[] }
//   GraphEdge: { agent_id (source), peer_agent_id (target), trust_weight }
// Returns { nodes, links } ready for AgentNetworkGraph.
export async function getTrustGraph(seedDid?: string): Promise<{
  nodes: { id: string; trust: number }[];
  links: { source: string; target: string }[];
}> {
  if (!seedDid) {
    const top = await getTopAgents();
    const first = Array.isArray(top) ? (top[0]?.agent_did as string) : undefined;
    if (!first) return { nodes: [], links: [] };
    seedDid = first;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const data = await get<any>(`/agents/${seedDid}/trust-network`);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const peers: any[] = Array.isArray(data?.peers) ? data.peers : [];

  // Build node set: seed agent at trust=1.0 + all unique peers
  const nodeMap = new Map<string, { id: string; trust: number }>();
  nodeMap.set(seedDid, { id: seedDid, trust: 1.0 });
  peers.forEach((p) => {
    const peerId = p.peer_agent_id as string;
    if (!nodeMap.has(peerId))
      nodeMap.set(peerId, { id: peerId, trust: (p.trust_weight as number) ?? 0.5 });
  });

  return {
    nodes: Array.from(nodeMap.values()),
    links: peers.map((p) => ({
      source: p.agent_id as string,
      target: p.peer_agent_id as string,
    })),
  };
}

// ── Communities ─────────────────────────────────────────────────────────────
export const getCommunities = (limit = 20)         => getList("/communities", { limit });
export const getCommunity   = (id: string)         => get<Record<string, unknown>>(`/communities/${id}`);
export const getThreads     = (communityId: string) => getList(`/communities/${communityId}/threads`);
export const getThread      = (threadId: string)   => get<Record<string, unknown>>(`/threads/${threadId}`);
export const getComments    = (threadId: string)   => getList(`/threads/${threadId}/comments`);
export const postComment    = (threadId: string, content: string) =>
  post<Record<string, unknown>>(`/threads/${threadId}/comments`, { content });

// ── Markets ─────────────────────────────────────────────────────────────────
export const getMarkets    = ()                    => getList("/markets/bounties");
export const getTasks      = (limit = 20)          => getList("/tasks", { limit });
export const getContracts  = ()                    => getList("/contracts");

// ── Notifications ────────────────────────────────────────────────────────────
export const getNotifications = ()                 => getList("/notifications");

// ── Messages ─────────────────────────────────────────────────────────────────
// Backend exposes GET /messages (list), not /messages/{did}
export const getMessages   = ()                    => getList("/messages");
