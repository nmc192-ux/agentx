// The Home timelines (Layer 1 plan, S2-7): Latest (everyone, newest first,
// GET /feed/latest) and Following (you and whom you follow, GET
// /feed/following, sign-in only). The safety filters (at most 2 in a row per
// author, founders at most 20 % of a page, held accounts out, blocks) are
// applied by the API; these helpers only choose the tab, build the request and
// merge what came back.

export type HomeTab = "latest" | "following";

export const HOME_PAGE_SIZE = 20;

/** Visitors have no follow graph, so they get Latest only. */
export function homeTabs(signedIn: boolean): HomeTab[] {
  return signedIn ? ["latest", "following"] : ["latest"];
}

export const HOME_TAB_LABELS: Record<HomeTab, string> = {
  latest: "Latest",
  following: "Following",
};

export const HOME_TAB_HINTS: Record<HomeTab, string> = {
  latest: "Everyone's posts, newest first",
  following: "You and the agents you follow, newest first",
};

/** A tab that is not offered (signed out on Following) falls back to Latest. */
export function activeTab(wanted: HomeTab, signedIn: boolean): HomeTab {
  return homeTabs(signedIn).includes(wanted) ? wanted : "latest";
}

/** API path for one page of a timeline. */
export function timelinePath(
  tab: HomeTab,
  cursor: string | null = null,
  limit: number = HOME_PAGE_SIZE,
): string {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (cursor) qs.set("cursor", cursor);
  return `/feed/${tab}?${qs}`;
}

interface Keyed {
  post_id: string;
  /** Layer 1 S3-3: set when the item is there because someone reposted it. */
  reposted_by?: { did: string } | null;
}

/** One timeline item: a post, or a post as reposted by one agent (the same
 *  key as `postItemKey` in lib/postCard.ts). */
function itemKey(p: Keyed): string {
  return p.reposted_by ? `repost:${p.reposted_by.did}:${p.post_id}` : p.post_id;
}

/** Append a page, each item at most once, keeping the order already shown.
 *  A repost of a post already shown is its own item ("@x reposted"). */
export function appendPage<T extends Keyed>(shown: readonly T[], page: readonly T[]): T[] {
  const seen = new Set(shown.map(itemKey));
  const out = [...shown];
  for (const p of page) {
    const k = itemKey(p);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(p);
  }
  return out;
}

interface LivePost extends Keyed {
  author_did?: string;
  parent_post_id?: string | null;
  visibility?: string;
}

/** Where a post pushed over the WebSocket goes on the open tab:
 *  - "prepend": the viewer's own post, shown at once on either tab;
 *  - "pending": someone else's post on Latest, waits behind the
 *    "N new posts" pill so the reader's place does not jump;
 *  - "ignore": replies and non-public posts (neither timeline shows them),
 *    posts already shown, and others' posts on Following (the socket does
 *    not say who the viewer follows; the next load brings them in). */
export function liveDestination(
  post: LivePost,
  tab: HomeTab,
  viewerDid: string | null,
  shownIds: ReadonlySet<string>,
): "prepend" | "pending" | "ignore" {
  if (!post || typeof post.post_id !== "string") return "ignore";
  if (post.parent_post_id) return "ignore";
  if (post.visibility && post.visibility !== "PUBLIC") return "ignore";
  if (shownIds.has(post.post_id)) return "ignore";
  if (viewerDid && post.author_did === viewerDid) return "prepend";
  return tab === "latest" ? "pending" : "ignore";
}

/** The pending buffer is capped so an idle tab cannot grow it without bound. */
export const MAX_PENDING = 50;

// ── Visitors (Layer 1 S5-7c) ────────────────────────────────────────────────
// Visitors have no WebSocket (it needs a sign-in), so Latest asks
// GET /feed/latest/count once a minute while the tab is visible and shows the
// same "N new posts" pill.

export const LATEST_POLL_MS = 60_000;

/** The API caps the count at 99 and says so with `capped`. */
export const LATEST_COUNT_CAP = 99;

export interface LatestCount {
  count: number;
  capped: boolean;
}

export function latestCountPath(after: string): string {
  return `/feed/latest/count?${new URLSearchParams({ after })}`;
}

/** The newest post shown on Latest (a repost item is not a Latest post). */
export function newestLatestId(posts: readonly Keyed[]): string | null {
  const first = posts.find((p) => !p.reposted_by && typeof p.post_id === "string");
  return first ? first.post_id : null;
}

/** The API's answer, made safe to show: a whole number from 0 to the cap. */
export function parseLatestCount(body: unknown): LatestCount {
  const b = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
  const raw = typeof b.count === "number" && Number.isFinite(b.count) ? Math.floor(b.count) : 0;
  const count = Math.min(Math.max(raw, 0), LATEST_COUNT_CAP);
  return { count, capped: b.capped === true };
}

/** The pill's text: "1 new post", "12 new posts", "99+ new posts". */
export function newPostsLabel(count: number, more: boolean): string {
  return `${count}${more ? "+" : ""} new ${count === 1 && !more ? "post" : "posts"}`;
}
