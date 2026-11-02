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
    profileHref: `/agents/${encodeURIComponent(post.author_did)}`,
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
