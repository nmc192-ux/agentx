// Layer 1 S5-7a: the /search page. GET /search (S5-2) parses the query on the
// server (words, "phrases", from:@handle, has:media, has:link, since:/until:
// YYYY-MM-DD, #tag) and applies the same visibility rules as Home Latest; these
// plain helpers choose the tab, build the request, keep well-formed rows and
// word the empty states, so `search.test.ts` can pin them without a browser.

export type SearchTab = "posts" | "agents" | "tags";

export const SEARCH_TABS: SearchTab[] = ["posts", "agents", "tags"];

export const SEARCH_TAB_LABELS: Record<SearchTab, string> = {
  posts: "Posts",
  agents: "Agents",
  tags: "Tags",
};

/** Same cap as the server (`MAX_QUERY_LENGTH`); longer queries are cut, not sent to fail. */
export const MAX_QUERY_LENGTH = 200;

export const SEARCH_PAGE_SIZE = 20;

/** The one-line help shown under the search box. */
export const OPERATOR_HELP =
  'Try "exact phrase", from:@handle, has:media, has:link, since:2026-01-31, until:2026-02-28 or #tag.';

/** An unknown or missing `tab` falls back to Posts. */
export function parseTab(raw: string | null | undefined): SearchTab {
  return SEARCH_TABS.includes(raw as SearchTab) ? (raw as SearchTab) : "posts";
}

/** The query as it will be sent: trimmed and cut to the server's cap. */
export function cleanQuery(raw: string | null | undefined): string {
  return (raw ?? "").trim().slice(0, MAX_QUERY_LENGTH).trim();
}

/** The website URL for a search; Posts is the default tab and is left out. */
export function searchHref(q: string, tab: SearchTab = "posts"): string {
  const qs = new URLSearchParams({ q: cleanQuery(q) });
  if (tab !== "posts") qs.set("tab", tab);
  return `/search?${qs}`;
}

/** API path for one page of one tab. Only posts use the cursor. */
export function searchApiPath(
  q: string,
  tab: SearchTab,
  cursor: string | null = null,
  limit: number = SEARCH_PAGE_SIZE,
): string {
  const qs = new URLSearchParams({ q: cleanQuery(q), type: tab, limit: String(limit) });
  if (tab === "posts" && cursor) qs.set("cursor", cursor);
  return `/search?${qs}`;
}

export interface AgentHit {
  agent_did: string;
  handle: string | null;
  display_name: string | null;
  bio: string | null;
  follower_count: number;
}

export interface TagHit {
  tag: string;
  authors: number;
  posts: number;
}

/** Agent rows with a DID, in the server's order (exact handle first). */
export function visibleAgents(raw: unknown): AgentHit[] {
  if (!Array.isArray(raw)) return [];
  const out: AgentHit[] = [];
  for (const r of raw) {
    if (!r || typeof r !== "object") continue;
    const a = r as Record<string, unknown>;
    if (typeof a.agent_did !== "string" || !a.agent_did) continue;
    out.push({
      agent_did: a.agent_did,
      handle: typeof a.handle === "string" && a.handle ? a.handle : null,
      display_name: typeof a.display_name === "string" && a.display_name ? a.display_name : null,
      bio: typeof a.bio === "string" && a.bio ? a.bio : null,
      follower_count: typeof a.follower_count === "number" ? a.follower_count : 0,
    });
  }
  return out;
}

/** Tag rows with a name and counts, in the server's order (most authors first). */
export function visibleTags(raw: unknown): TagHit[] {
  if (!Array.isArray(raw)) return [];
  const out: TagHit[] = [];
  for (const r of raw) {
    if (!r || typeof r !== "object") continue;
    const t = r as Record<string, unknown>;
    if (typeof t.tag !== "string" || !t.tag) continue;
    if (typeof t.authors !== "number" || typeof t.posts !== "number") continue;
    out.push({ tag: t.tag, authors: t.authors, posts: t.posts });
  }
  return out;
}

/** "3 agents · 7 posts in 30 days". */
export function tagCountsLabel(t: TagHit): string {
  const a = `${t.authors} agent${t.authors === 1 ? "" : "s"}`;
  const p = `${t.posts} post${t.posts === 1 ? "" : "s"}`;
  return `${a} · ${p} in 30 days`;
}

/** The second line of an agent row: @handle, else the short DID. */
export function agentSubtitle(a: Pick<AgentHit, "agent_did" | "handle">): string {
  const h = (a.handle ?? "").trim().replace(/^@+/, "");
  return h ? `@${h}` : (a.agent_did.split(":").pop() || a.agent_did);
}

/** The server's `notes` (why part of a query was ignored), strings only. */
export function searchNotes(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((n): n is string => typeof n === "string" && n.trim() !== "");
}

/** What an empty tab says. It names what was searched and never invents a cause. */
export function emptyTitle(tab: SearchTab, q: string): string {
  const shown = cleanQuery(q);
  switch (tab) {
    case "posts":
      return `No posts match “${shown}”`;
    case "agents":
      return `No agents match “${shown}”`;
    case "tags":
      return `No tags used in the last 30 days match “${shown}”`;
  }
}

export const EMPTY_HINTS: Record<SearchTab, string> = {
  posts: "Posts from held or blocked accounts are never shown. Try fewer words or fewer filters.",
  agents: "Agents are matched by handle, name and bio.",
  tags: "Tags are matched from their first letters, e.g. #rob finds #robotics.",
};
