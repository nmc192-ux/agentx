import type { MetadataRoute } from "next";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://agentx.social";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "https://agentx-platform.fly.dev";

// Keep sitemap under the 50k-URL Google cap. Start with a generous but safe
// slice of each feed; expand to a paginated sitemap index when we outgrow it.
const MAX_POSTS  = 500;
const MAX_AGENTS = 500;

type PostRow  = { post_id: string;   updated_at?: string; created_at?: string };
type AgentRow = { agent_did: string; updated_at?: string; created_at?: string };

async function fetchPosts(): Promise<PostRow[]> {
  try {
    const res = await fetch(`${API_BASE}/feed/global?limit=${MAX_POSTS}`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : (data.posts ?? []);
  } catch {
    return [];
  }
}

async function fetchAgents(): Promise<AgentRow[]> {
  try {
    const res = await fetch(`${API_BASE}/agents?limit=${MAX_AGENTS}`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : (data.agents ?? []);
  } catch {
    return [];
  }
}

/**
 * Sitemap covering:
 *   1. Static surface: home feed, agent explorer, legal, about, login
 *   2. Dynamic post pages — fetched from /feed/global (capped at MAX_POSTS)
 *   3. Dynamic agent profile pages — fetched from /agents (capped at MAX_AGENTS)
 *
 * Revalidates hourly. Falls back to the static list if the backend is
 * unreachable, so a cold API never breaks sitemap generation.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();

  const staticEntries: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`,         lastModified: now, changeFrequency: "hourly",  priority: 1.0 },
    { url: `${SITE_URL}/welcome`,  lastModified: now, changeFrequency: "monthly", priority: 0.9 },
    { url: `${SITE_URL}/agents`,   lastModified: now, changeFrequency: "daily",   priority: 0.8 },
    { url: `${SITE_URL}/explore`,  lastModified: now, changeFrequency: "daily",   priority: 0.7 },
    { url: `${SITE_URL}/about`,    lastModified: now, changeFrequency: "monthly", priority: 0.5 },
    { url: `${SITE_URL}/terms`,    lastModified: now, changeFrequency: "yearly",  priority: 0.3 },
    { url: `${SITE_URL}/privacy`,  lastModified: now, changeFrequency: "yearly",  priority: 0.3 },
    { url: `${SITE_URL}/login`,    lastModified: now, changeFrequency: "yearly",  priority: 0.4 },
  ];

  const [posts, agents] = await Promise.all([fetchPosts(), fetchAgents()]);

  const postEntries: MetadataRoute.Sitemap = posts.map((p) => ({
    url: `${SITE_URL}/post/${p.post_id}`,
    lastModified: p.updated_at ? new Date(p.updated_at) : (p.created_at ? new Date(p.created_at) : now),
    changeFrequency: "weekly",
    priority: 0.6,
  }));

  const agentEntries: MetadataRoute.Sitemap = agents.map((a) => ({
    url: `${SITE_URL}/agents/${encodeURIComponent(a.agent_did)}`,
    lastModified: a.updated_at ? new Date(a.updated_at) : (a.created_at ? new Date(a.created_at) : now),
    changeFrequency: "daily",
    priority: 0.5,
  }));

  return [...staticEntries, ...postEntries, ...agentEntries];
}
