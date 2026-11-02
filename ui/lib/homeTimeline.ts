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
}

/** Append a page, each post at most once, keeping the order already shown. */
export function appendPage<T extends Keyed>(shown: readonly T[], page: readonly T[]): T[] {
  const seen = new Set(shown.map((p) => p.post_id));
  const out = [...shown];
  for (const p of page) {
    if (seen.has(p.post_id)) continue;
    seen.add(p.post_id);
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
