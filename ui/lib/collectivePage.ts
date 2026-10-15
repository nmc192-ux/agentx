/**
 * Group page logic (Sprint 22, CL-5), kept free of React and imports so
 * `node --test` can run it directly.
 */

/** The API's limit on a join note (`JoinRequest.message`). */
export const JOIN_MESSAGE_MAX = 500;

/**
 * What the membership panel offers, from the caller's own standing
 * (GET /collectives/{id}/membership):
 * - "signin":  nobody is signed in; the button sends them to /login
 * - "loading": signed in, standing not known yet
 * - "ask":     no row (never asked, or left) — "Ask to join"
 * - "pending": asked, waiting — "Request sent"
 * - "leave":   ACTIVE MEMBER or ADMIN — "Leave"
 * - "owner":   ACTIVE OWNER — cannot leave (the API refuses)
 * - "banned":  nothing to offer
 */
export type MembershipAction = "signin" | "loading" | "ask" | "pending" | "leave" | "owner" | "banned";

export function membershipAction(
  signedIn: boolean,
  membership: { role: string | null; status: string } | null,
): MembershipAction {
  if (!signedIn) return "signin";
  if (!membership) return "loading";
  const status = membership.status.toUpperCase();
  if (status === "NONE") return "ask";
  if (status === "PENDING") return "pending";
  if (status === "BANNED") return "banned";
  if (status === "ACTIVE") return membership.role === "OWNER" ? "owner" : "leave";
  return "ask";
}

/** Only an ACTIVE OWNER or ADMIN may read and approve pending requests. */
export function canManageRequests(membership: { role: string | null; status: string } | null): boolean {
  if (!membership || membership.status.toUpperCase() !== "ACTIVE") return false;
  return membership.role === "OWNER" || membership.role === "ADMIN";
}

/** Error for the join note, or null when it can be sent. */
export function joinMessageError(message: string): string | null {
  if (message.trim().length > JOIN_MESSAGE_MAX) return `A note is at most ${JOIN_MESSAGE_MAX} characters.`;
  return null;
}

/** The join body's note: trimmed, blank sent as null. */
export function joinMessageBody(message: string): string | null {
  const m = message.trim();
  return m ? m : null;
}

/**
 * Text for an API refusal on this page. A plain-string detail is shown as it
 * is; a 422 lists its problems; anything else gets a short fallback.
 */
export function actionErrorText(status: number, detail: unknown, action: string): string {
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  if (status === 401) return `Your sign-in has expired. Sign in again to ${action}.`;
  return `Could not ${action} (error ${status}). Try again in a moment.`;
}

/** "in_progress" → "In progress". */
export function statusLabel(status: string): string {
  const s = status.replace(/_/g, " ").trim().toLowerCase();
  return s ? s[0].toUpperCase() + s.slice(1) : "Unknown";
}

/** Counts by status, largest first, ties by name — for the work summary. */
export function sortedCounts(counts: Record<string, number>): [string, number][] {
  return Object.entries(counts)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** Where a signed-out visitor is sent: the login page, coming back here. */
export function loginPathFor(collectiveId: string): string {
  return `/login?next=${encodeURIComponent(`/groups/${collectiveId}`)}`;
}

/** Loose UUID shape check, so a junk path is a 404 without asking the API. */
export function looksLikeUuid(id: string): boolean {
  return /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(id);
}
