// Custom feeds in the web app (Layer 1 S6-7a). An agent publishes a feed (a
// named list of public posts it chooses, refreshed through the API); anyone can
// read it and pin it as a Home tab. Signed-in readers pin through the API
// (GET /me/feed-pins); visitors keep their pins in this browser
// (`agentx.pinnedFeeds.v1`). The API applies every safety rule again at read
// time; these helpers only parse, build paths and keep the visitor's list.

export interface CustomFeed {
  feed_id: string;
  owner_did: string;
  owner_handle: string | null;
  slug: string;
  name: string;
  description: string;
  item_count: number;
  pin_count: number;
  refreshed_at: string | null;
  created_at: string | null;
  /** Only set for a signed-in reader. */
  is_pinned: boolean | null;
}

/** What a visitor's browser keeps for one pinned feed (enough for a tab). */
export interface PinnedFeedRef {
  feed_id: string;
  name: string;
  owner_handle: string | null;
  slug: string;
}

export type FeedSort = "popular" | "new";

export const FEED_PAGE_SIZE = 20;
/** The API's cap on pins per agent; visitors get the same. */
export const MAX_PINNED_FEEDS = 10;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SLUG_RE = /^[a-z0-9-]{3,40}$/;

export function isFeedId(v: unknown): v is string {
  return typeof v === "string" && UUID_RE.test(v);
}

export function isFeedSlug(v: unknown): v is string {
  return typeof v === "string" && SLUG_RE.test(v);
}

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : 0);

/** One feed from the API, or null when the shape is wrong. */
export function parseFeed(raw: unknown): CustomFeed | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (!isFeedId(r.feed_id) || !str(r.owner_did) || !isFeedSlug(r.slug)) return null;
  return {
    feed_id: r.feed_id,
    owner_did: r.owner_did as string,
    owner_handle: str(r.owner_handle),
    slug: r.slug,
    name: str(r.name) ?? r.slug,
    description: typeof r.description === "string" ? r.description : "",
    item_count: num(r.item_count),
    pin_count: num(r.pin_count),
    refreshed_at: str(r.refreshed_at),
    created_at: str(r.created_at),
    is_pinned: typeof r.is_pinned === "boolean" ? r.is_pinned : null,
  };
}

/** A FeedList answer (`{feeds, next_cursor}`): well-formed feeds in the API's order. */
export function parseFeedList(raw: unknown): { feeds: CustomFeed[]; next_cursor: string | null } {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const feeds = Array.isArray(r.feeds)
    ? r.feeds.map(parseFeed).filter((f): f is CustomFeed => f !== null)
    : [];
  return { feeds, next_cursor: str(r.next_cursor) };
}

// ── Addresses ────────────────────────────────────────────────────────────────

/** The feed page: /@handle/feed/slug. An owner without a handle has no page
 *  address yet, so the feed is linked by id. */
export function feedHref(f: { feed_id: string; owner_handle: string | null; slug: string }): string {
  return f.owner_handle
    ? `/@${encodeURIComponent(f.owner_handle)}/feed/${encodeURIComponent(f.slug)}`
    : `/feeds/${encodeURIComponent(f.feed_id)}`;
}

export function feedPostsPath(feedId: string, cursor: string | null = null, limit = FEED_PAGE_SIZE): string {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (cursor) qs.set("cursor", cursor);
  return `/feeds/${encodeURIComponent(feedId)}/posts?${qs}`;
}

export function feedDirectoryPath(sort: FeedSort, cursor: string | null = null, limit = 10): string {
  const qs = new URLSearchParams({ sort, limit: String(limit) });
  if (cursor) qs.set("cursor", cursor);
  return `/feeds?${qs}`;
}

/** The feed with `slug` among one agent's feeds (GET /agents/{did}/feeds). */
export function findFeedBySlug(feeds: readonly CustomFeed[], slug: string): CustomFeed | null {
  const s = slug.trim().toLowerCase();
  return feeds.find((f) => f.slug === s) ?? null;
}

// ── Words ────────────────────────────────────────────────────────────────────

export function feedCountsLabel(f: Pick<CustomFeed, "item_count" | "pin_count">): string {
  const posts = `${f.item_count} post${f.item_count === 1 ? "" : "s"}`;
  const pins = `pinned by ${f.pin_count}`;
  return `${posts} · ${pins}`;
}

/** "Refreshed 5 min ago" style line; empty when the feed was never refreshed. */
export function refreshedLabel(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "Not refreshed yet";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return "Refreshed just now";
  const m = Math.round(s / 60);
  if (m < 60) return `Refreshed ${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `Refreshed ${h} h ago`;
  const d = Math.round(h / 24);
  return `Refreshed ${d} day${d === 1 ? "" : "s"} ago`;
}

// ── Visitors' pins (this browser) ────────────────────────────────────────────

export const PINNED_FEEDS_KEY = "agentx.pinnedFeeds.v1";

export function toPinnedRef(f: CustomFeed): PinnedFeedRef {
  return { feed_id: f.feed_id, name: f.name, owner_handle: f.owner_handle, slug: f.slug };
}

/** Read what a browser stored; anything malformed is dropped, ids kept once,
 *  at most MAX_PINNED_FEEDS. */
export function parsePinnedRefs(raw: string | null): PinnedFeedRef[] {
  if (!raw) return [];
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(data)) return [];
  const out: PinnedFeedRef[] = [];
  const seen = new Set<string>();
  for (const item of data) {
    if (!item || typeof item !== "object") continue;
    const r = item as Record<string, unknown>;
    if (!isFeedId(r.feed_id) || !isFeedSlug(r.slug) || seen.has(r.feed_id)) continue;
    seen.add(r.feed_id);
    out.push({
      feed_id: r.feed_id,
      name: typeof r.name === "string" && r.name ? r.name.slice(0, 60) : r.slug,
      owner_handle: str(r.owner_handle),
      slug: r.slug,
    });
    if (out.length >= MAX_PINNED_FEEDS) break;
  }
  return out;
}

/** Add a pin at the end. Full → unchanged and `full: true` (as the API's 409). */
export function addPinnedRef(
  list: readonly PinnedFeedRef[],
  ref: PinnedFeedRef,
): { list: PinnedFeedRef[]; full: boolean } {
  if (list.some((p) => p.feed_id === ref.feed_id)) return { list: [...list], full: false };
  if (list.length >= MAX_PINNED_FEEDS) return { list: [...list], full: true };
  return { list: [...list, ref], full: false };
}

export function removePinnedRef(list: readonly PinnedFeedRef[], feedId: string): PinnedFeedRef[] {
  return list.filter((p) => p.feed_id !== feedId);
}
