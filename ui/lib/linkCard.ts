/**
 * Layer 1 S4-10b: the link card under a post, and the moderators' image
 * review page.
 *
 * Pure helpers (tested in linkCard.test.ts). The server fetches the card
 * for a post's first link in a background job (S4-7) and re-hosts its
 * image under /media/, so the card never loads anything from the linked
 * site. Only http(s) links are ever made clickable.
 */
export const MAX_CARD_TITLE = 200;
export const MAX_CARD_DESCRIPTION = 500;
export const MAX_CARD_SITE = 200;

/** Every outside link on a card opens with these. */
export const CARD_REL = "noopener noreferrer nofollow";

export interface LinkCardData {
  url:          string;
  title?:       string | null;
  description?: string | null;
  site_name?:   string | null;
  image?:       { url: string; width: number; height: number } | null;
}

export interface LinkCardView {
  href:        string;
  host:        string;
  title:       string;
  description: string | null;
  site:        string;
  imageSrc:    string | null;
}

function cleanText(value: unknown, max: number): string | null {
  if (typeof value !== "string") return null;
  // Plain text only: collapse whitespace (incl. line breaks) and drop
  // control characters, then cap at the server's own limit.
  const t = value.replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim();
  return t ? t.slice(0, max) : null;
}

/** A safe http(s) URL, or null (`javascript:`, `data:`, credentials, …). */
export function safeLinkHref(url: unknown): { href: string; host: string } | null {
  if (typeof url !== "string" || url.length > 2048) return null;
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return null;
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") return null;
  if (!u.hostname || u.username || u.password) return null;
  return { href: u.href, host: u.hostname.replace(/^www\./, "") };
}

/** What the card shows, or null when there is nothing safe to show. The
 *  image is the re-hosted /media/ copy only, never an outside address:
 *  `imageSrc` is `postMedia.mediaSrc` bound to the API base, which refuses
 *  everything but the server's own file paths. */
export function linkCardView(
  card: unknown,
  imageSrc: (url: unknown) => string | null,
): LinkCardView | null {
  if (!card || typeof card !== "object") return null;
  const c = card as LinkCardData;
  const link = safeLinkHref(c.url);
  if (!link) return null;
  const site = cleanText(c.site_name, MAX_CARD_SITE) ?? link.host;
  const title = cleanText(c.title, MAX_CARD_TITLE) ?? link.host;
  const src = c.image && typeof c.image === "object" ? imageSrc(c.image.url) : null;
  return {
    href: link.href,
    host: link.host,
    title,
    description: cleanText(c.description, MAX_CARD_DESCRIPTION),
    site,
    imageSrc: src,
  };
}

/** A card only when the post has no images (as on X: images win). */
export function showLinkCard(media: unknown, card: unknown): boolean {
  if (Array.isArray(media) && media.length > 0) return false;
  return card !== null && card !== undefined;
}

// ── Image review (GET /media/moderation/queue, approve, reject) ──────────────

export const MODERATOR_ROLES = ["FOUNDER", "OPERATOR"] as const;

/** Same roles as the server's `services/post_moderation.MODERATOR_ROLES`. */
export function isModerator(role: unknown): boolean {
  return typeof role === "string" && (MODERATOR_ROLES as readonly string[]).includes(role);
}

/** "3 days old", "5 hours old", "just joined": how new the owner is. */
export function accountAgeText(createdAt: string | null | undefined, now: number): string {
  if (!createdAt) return "account age unknown";
  const t = Date.parse(createdAt);
  if (Number.isNaN(t)) return "account age unknown";
  const hours = Math.max(0, Math.floor((now - t) / 3_600_000));
  if (hours < 1) return "just joined";
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"} old`;
  const days = Math.floor(hours / 24);
  return `${days} days old`;
}

/** Plain words for a failed queue load. */
export function queueErrorText(status: number): string {
  if (status === 401) return "Sign in again to review images.";
  if (status === 403) return "Only FOUNDER and OPERATOR accounts can review images.";
  return "Could not load the images waiting for review. Try again.";
}

/** Plain words for a failed approve / reject, from the status and the
 *  server's `detail.code`. */
export function reviewErrorText(status: number, body: unknown): string {
  const detail = (body as { detail?: { code?: unknown } } | null)?.detail;
  const code = detail && typeof detail === "object" ? detail.code : undefined;
  if (code === "post_hidden") return "Its post is hidden. Unhide the post first, then approve.";
  if (code === "not_pending") return "Someone already reviewed this image.";
  if (code === "already_rejected") return "This image is already rejected.";
  if (code === "media_changed") return "The image changed while you looked at it. Try again.";
  if (status === 404) return "This image no longer exists.";
  if (status === 401) return "Sign in again to review images.";
  if (status === 403) return "Only FOUNDER and OPERATOR accounts can review images.";
  return "Could not save your decision. Try again.";
}
