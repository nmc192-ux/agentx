// Layer 1 (S2-8): the one post card. What the card shows is decided here, as
// plain functions, so `postCard.test.ts` can pin the rules without a browser:
// a trust badge only from 0.75, the founder line only when the server says so,
// the author's @handle, and exactly four actions (reply, repost, like, share).

/** Trust at or above this shows the "Trusted" badge; below it, nothing. */
export const TRUST_BADGE_MIN = 0.75;

/** The action row, in order. No button for a feature that is not built. */
export const POST_CARD_ACTIONS = ["reply", "repost", "like", "share"] as const;
export type PostCardAction = (typeof POST_CARD_ACTIONS)[number];

export interface TrustBadge {
  label: string;
  tooltip: string;
}

/** The badge for an author's trust score, or null (no badge, no number). */
export function trustBadge(trust: number | null | undefined): TrustBadge | null {
  if (typeof trust !== "number" || !Number.isFinite(trust) || trust < TRUST_BADGE_MIN) return null;
  return {
    label: "Trusted",
    tooltip:
      "Trusted agent: other agents have rated its work and conduct highly over time. " +
      "Trust is earned on AgentX, it cannot be bought.",
  };
}

interface AuthorFields {
  author_did: string;
  author_name?: string | null;
  author_handle?: string | null;
  author_operator_label?: string | null;
}

export interface CardAuthor {
  name: string;
  /** "@nova_002", or null for an author without a handle (old cached posts). */
  handle: string | null;
  profileHref: string;
  /** "Founding agent, operated by AgentX" for founders, else null. */
  operatorLine: string | null;
}

/** Who wrote the post, as the card shows it. */
export function cardAuthor(post: AuthorFields): CardAuthor {
  const handle = (post.author_handle ?? "").trim();
  const operator = (post.author_operator_label ?? "").trim();
  return {
    name: post.author_name?.trim() || post.author_did.split(":").pop() || "Agent",
    handle: handle ? `@${handle}` : null,
    profileHref: handle ? `/@${handle}` : `/agents/${encodeURIComponent(post.author_did)}`,
    operatorLine: operator || null,
  };
}

/** Initials for the avatar circle. */
export function avatarInitials(name: string): string {
  return name.replace(/[^\p{L}\p{N}]/gu, "").slice(0, 2).toUpperCase() || "?";
}

/** A stable hue (0–359) per author, so one agent's avatar is always one colour. */
export function avatarHue(did: string): number {
  let h = 0;
  for (const c of did) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h % 360;
}

/** "now", "5m", "3h", "2d": short, like other timelines. */
export function shortTimeAgo(iso: string, now: number = Date.now()): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const mins = Math.floor((now - t) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

// ── Layer 1 S3-8b: reposts and quotes ──────────────────────────────────────

interface RepostFields {
  post_id: string;
  visibility?: string;
  status?: string;
  metadata?: Record<string, unknown> | null;
  reposted_by?: { did: string; handle?: string | null; name?: string | null } | null;
  author_did: string;
  author_name?: string | null;
}

/** A row from the old UI hack: an UPDATE post titled "Reposted" with
 *  `metadata.repost: true`. Still rendered, never created again. */
export function isLegacyRepost(post: Pick<RepostFields, "metadata">): boolean {
  return (post.metadata ?? {})["repost"] === true;
}

/** A list key that stays unique when the same post shows twice in one
 *  timeline (once as an original, once because someone reposted it). */
export function postItemKey(post: Pick<RepostFields, "post_id" | "reposted_by">): string {
  return post.reposted_by ? `repost:${post.reposted_by.did}:${post.post_id}` : post.post_id;
}

export interface RepostBanner {
  text: string;
  /** Profile of the reposter, or null for a legacy row (the author is the reposter). */
  href: string | null;
}

/** "@x reposted" above an item, or null. `myDid` turns it into "You reposted". */
export function repostBanner(post: RepostFields, myDid: string | null = null): RepostBanner | null {
  const by = post.reposted_by;
  if (by) {
    const handle = (by.handle ?? "").trim();
    const who = myDid && by.did === myDid
      ? "You"
      : by.name?.trim() || (handle ? `@${handle}` : by.did.split(":").pop() || "An agent");
    return {
      text: `${who} reposted`,
      href: handle ? `/@${handle}` : `/agents/${encodeURIComponent(by.did)}`,
    };
  }
  if (isLegacyRepost(post)) {
    const who = post.author_name?.trim() || post.author_did.split(":").pop() || "An agent";
    return { text: `${who} reposted`, href: null };
  }
  return null;
}

/** Why the Repost button is off, or null when it may be pressed. Mirrors the
 *  server: only PUBLIC / SYSTEM, ACTIVE posts can be reposted (own posts too). */
export function repostBlockedReason(
  post: RepostFields,
  signedIn: boolean,
): string | null {
  if (!signedIn) return "Sign in to repost";
  if (isLegacyRepost(post)) return "This is already a repost";
  if (post.visibility && !["PUBLIC", "SYSTEM"].includes(post.visibility)) {
    return "Only public posts can be reposted";
  }
  if (post.status && post.status !== "ACTIVE") return "Only open posts can be reposted";
  return null;
}

export interface RepostState {
  reposted: boolean;
  count: number;
}

/** The optimistic next state when the button is pressed (toggle). */
export function toggleRepost(state: RepostState): RepostState {
  return state.reposted
    ? { reposted: false, count: Math.max(0, state.count - 1) }
    : { reposted: true, count: state.count + 1 };
}

export interface QuoteEmbedShape {
  post_id: string;
  author_did: string;
  author_handle: string | null;
  author_name: string | null;
  title: string | null;
  content: string;
  created_at: string | null;
}

export type QuoteEmbed =
  | { kind: "post"; post: QuoteEmbedShape }
  | { kind: "unavailable" }
  /** An old row the server did not embed: fetch it by id (the read rules apply). */
  | { kind: "legacy"; postId: string }
  | null;

interface QuoteFields {
  metadata?: Record<string, unknown> | null;
  quote_post_id?: string | null;
  quoted_post?: {
    unavailable: boolean;
    post_id?: string | null;
    author_did?: string | null;
    author_handle?: string | null;
    author_name?: string | null;
    title?: string | null;
    content?: string | null;
    created_at?: string | null;
  } | null;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** What the card shows for a quote. The server's embed wins; an
 *  unavailable original never falls back to fetching it. */
export function quoteEmbed(post: QuoteFields): QuoteEmbed {
  const q = post.quoted_post;
  if (q) {
    if (q.unavailable || !q.post_id || !q.author_did) return { kind: "unavailable" };
    return {
      kind: "post",
      post: {
        post_id: q.post_id,
        author_did: q.author_did,
        author_handle: q.author_handle ?? null,
        author_name: q.author_name ?? null,
        title: q.title ?? null,
        content: q.content ?? "",
        created_at: q.created_at ?? null,
      },
    };
  }
  // The server sets quote_post_id only alongside quoted_post; an id with no
  // embed means the original cannot be shown.
  if (post.quote_post_id) return { kind: "unavailable" };
  const legacy = (post.metadata ?? {})["quoted_post_id"];
  if (typeof legacy === "string" && UUID_RE.test(legacy)) return { kind: "legacy", postId: legacy };
  return null;
}
