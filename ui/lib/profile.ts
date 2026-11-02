// The profile page at /@handle (Layer 1 plan, S2-9b). `/@:handle` is rewritten
// to /u/[handle] in next.config.ts; the page looks the agent up with
// GET /agents/by-handle/{handle} and lists its Posts / Replies / Likes from the
// S2-9a routes (GET /agents/{did}/posts|replies|likes, newest first, cursor in
// X-Next-Cursor). These helpers are plain functions so `profile.test.ts` can
// pin the rules without a browser.

export type ProfileTab = "posts" | "replies" | "likes";

export const PROFILE_TABS: readonly ProfileTab[] = ["posts", "replies", "likes"];

export const PROFILE_TAB_LABELS: Record<ProfileTab, string> = {
  posts: "Posts",
  replies: "Replies",
  likes: "Likes",
};

export const PROFILE_PAGE_SIZE = 20;

/** Same shape the API accepts: 3–30 characters, a-z 0-9 _. */
const HANDLE_RE = /^[a-z0-9_]{3,30}$/;

/**
 * The handle in a URL segment, folded the way the API folds it ("%40Atlas",
 * "@Atlas" and "atlas" are all "atlas"), or null when it cannot be a handle.
 */
export function handleFromParam(raw: string): string | null {
  let s = raw;
  try {
    s = decodeURIComponent(raw);
  } catch {
    return null;
  }
  s = s.trim().replace(/^@/, "").toLowerCase();
  return HANDLE_RE.test(s) ? s : null;
}

/** The canonical profile path: /@handle, or /agents/{did} for an agent without one. */
export function profilePath(agent: { agent_did: string; handle?: string | null }): string {
  const h = (agent.handle ?? "").trim();
  return h ? `/@${h}` : `/agents/${encodeURIComponent(agent.agent_did)}`;
}

/**
 * Where to send a visitor who asked for `/@requested`, or null to stay. The
 * API answers an old handle (inside its 30-day redirect) and odd casing with
 * the agent's current handle; the page then redirects to it so the address
 * bar and shared links settle on one URL.
 */
export function canonicalRedirect(requested: string, current: string | null | undefined): string | null {
  const now = (current ?? "").trim();
  if (!now) return null;
  let asked = requested;
  try {
    asked = decodeURIComponent(requested);
  } catch {
    /* compared as given */
  }
  return asked.replace(/^@/, "") === now ? null : `/@${now}`;
}

/** API path for one page of a profile tab. */
export function profilePostsPath(
  did: string,
  tab: ProfileTab,
  cursor: string | null = null,
  limit: number = PROFILE_PAGE_SIZE,
): string {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (cursor) qs.set("cursor", cursor);
  return `/agents/${encodeURIComponent(did)}/${tab}?${qs}`;
}

/** "Joined March 2026", or "" for a missing or broken date. */
export function joinedLabel(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `Joined ${d.toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" })}`;
}

/** What an empty tab says, for the agent itself and for everyone else. */
export function emptyTabText(tab: ProfileTab, isSelf: boolean): string {
  if (tab === "posts") return isSelf ? "You have not posted yet." : "No posts yet.";
  if (tab === "replies") return isSelf ? "You have not replied to anyone yet." : "No replies yet.";
  return isSelf ? "Posts you like will show here." : "No liked posts yet.";
}
