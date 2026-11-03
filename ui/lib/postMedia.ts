/**
 * Layer 1 S4-10a: images on a post and the "Report post" action.
 *
 * Pure helpers (tested in postMedia.test.ts). The server sends `media` on
 * every post (S4-4) in grid order: a PENDING image has `url` and
 * `alt_text` null for everyone but its author and the moderators, who see
 * it through an authenticated fetch (the file is `private, no-store`).
 * Only the server's own file paths are ever rendered.
 */

export interface PostMediaItem {
  media_id: string;
  status:   string;
  url?:      string | null;
  alt_text?: string | null;
  width:    number;
  height:   number;
}

export const MAX_POST_MEDIA = 4;
export const PENDING_TEXT = "Image awaiting review";

/** `/media/{uuid}.{ext}` exactly, as `routers/media.media_url` builds it. */
const MEDIA_PATH_RE =
  /^\/media\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpg|png|webp|gif)$/;

/** The absolute file URL for a server media path, or null for anything
 *  else (an outside URL, `javascript:`, a path that leaves `/media/`). */
export function mediaSrc(url: string | null | undefined, base: string): string | null {
  if (typeof url !== "string" || !MEDIA_PATH_RE.test(url)) return null;
  return `${base.replace(/\/+$/, "")}${url}`;
}

export type MediaTile =
  | { kind: "image"; id: string; src: string; alt: string; width: number; height: number; authed: boolean }
  | { kind: "pending"; id: string };

/** What the grid shows, in order (at most 4). An APPROVED image is a plain
 *  `<img>`; a PENDING one with a url (the reader is its author or a
 *  moderator) needs the token (`authed`); a PENDING one without a url is
 *  the placeholder. REJECTED images and unusable urls show nothing. */
export function mediaTiles(media: unknown, base: string): MediaTile[] {
  if (!Array.isArray(media)) return [];
  const tiles: MediaTile[] = [];
  for (const raw of media) {
    if (tiles.length >= MAX_POST_MEDIA) break;
    if (!raw || typeof raw !== "object") continue;
    const m = raw as PostMediaItem;
    if (typeof m.media_id !== "string") continue;
    if (m.status !== "APPROVED" && m.status !== "PENDING") continue;
    const src = mediaSrc(m.url, base);
    if (src) {
      tiles.push({
        kind: "image", id: m.media_id, src,
        alt: typeof m.alt_text === "string" ? m.alt_text : "",
        width: Number(m.width) || 0, height: Number(m.height) || 0,
        authed: m.status === "PENDING",
      });
    } else if (m.status === "PENDING" && (m.url === null || m.url === undefined)) {
      tiles.push({ kind: "pending", id: m.media_id });
    }
  }
  return tiles;
}

/** Tailwind classes for the grid of `n` tiles (X-style: 1 wide, 2 side by
 *  side, 3 with the first tall, 4 as two rows). */
export function gridClass(n: number): string {
  if (n <= 1) return "grid grid-cols-1";
  if (n === 3) return "grid grid-cols-2 grid-rows-2";
  return "grid grid-cols-2";
}

/** Extra classes for tile `i` of `n` (the first of three spans both rows). */
export function tileClass(i: number, n: number): string {
  if (n === 1) return "max-h-[32rem]";
  if (n === 3 && i === 0) return "row-span-2 h-full";
  return "aspect-[4/3]";
}

/** Next / previous index in the lightbox, wrapping round. */
export function stepIndex(i: number, delta: number, n: number): number {
  if (n <= 0) return 0;
  return (((i + delta) % n) + n) % n;
}

// ── Report post (POST /posts/{id}/flag) ──────────────────────────────────────

/** The server's `PostFlagReason` values with the words the menu shows. */
export const FLAG_REASONS = [
  { value: "spam",         label: "Spam" },
  { value: "abuse",        label: "Abuse or harassment" },
  { value: "solicitation", label: "Asking for money or keys" },
  { value: "other",        label: "Something else" },
] as const;

export type FlagReason = (typeof FLAG_REASONS)[number]["value"];
export const MAX_FLAG_NOTE = 500;

/** Who may report: signed in, and not the author (the server refuses that). */
export function canReport(loggedIn: boolean, isOwnPost: boolean): boolean {
  return loggedIn && !isOwnPost;
}

/** The request body, or null when it would be refused. */
export function flagBody(reason: string, note: string): { reason: FlagReason; note?: string } | null {
  const r = FLAG_REASONS.find((f) => f.value === reason);
  if (!r) return null;
  const trimmed = note.trim();
  if (trimmed.length > MAX_FLAG_NOTE) return null;
  return trimmed ? { reason: r.value, note: trimmed } : { reason: r.value };
}

/** Plain words for the answer to a report. */
export function flagResultText(status: number | null): string {
  if (status === null) return "Thanks. A moderator will look at this post.";
  if (status === 409) return "You have already reported this post.";
  if (status === 401) return "Sign in again to report this post.";
  if (status === 429) return "Too many reports just now. Try again later.";
  if (status === 404) return "This post is no longer available.";
  if (status === 400 || status === 403) return "You cannot report this post.";
  return "Could not send the report. Try again.";
}
