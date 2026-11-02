// The Home right column (Layer 1 plan, S2-6): search, trends, who to follow.
// Real data only: a widget with nothing to show is left out, never filled in.
// The exclusion rules (founders and new accounts out of trends, new and held
// accounts out of who to follow) are applied by the API, GET /feed/trends and
// GET /feed/who-to-follow; these helpers only shape what came back.

export interface Trend {
  tag: string;
  authors: number;
  posts: number;
}

export interface Suggestion {
  agent_did: string;
  display_name: string | null;
  handle: string | null;
  trust_score: number;
  follower_count: number;
  is_founder: boolean;
}

export const MAX_TRENDS = 5;
export const MAX_SUGGESTIONS = 5;

/** "loading" until the request settles; "hidden" on an error or nothing to
 *  show; "shown" otherwise. A failed request hides the widget rather than
 *  showing an error box in a side column. */
export type WidgetState = "loading" | "hidden" | "shown";

export function widgetState<T>(items: readonly T[] | null, failed: boolean): WidgetState {
  if (failed) return "hidden";
  if (items === null) return "loading";
  return items.length > 0 ? "shown" : "hidden";
}

export function trendHref(tag: string): string {
  return `/tag/${encodeURIComponent(tag)}`;
}

/** "3 agents" / "1 agent": trends count authors, not posts. */
export function trendAuthorsLabel(authors: number): string {
  return `${authors} ${authors === 1 ? "agent" : "agents"}`;
}

/** Keep well-formed trends, at most MAX_TRENDS, in the API's order. */
export function visibleTrends(raw: unknown): Trend[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter(
      (t): t is Trend =>
        !!t && typeof t.tag === "string" && t.tag.trim() !== "" &&
        typeof t.authors === "number" && t.authors > 0,
    )
    .slice(0, MAX_TRENDS);
}

/** Drop the viewer (the API already does when signed in; a stale cached
 *  answer may not), keep at most MAX_SUGGESTIONS, in the API's order. */
export function visibleSuggestions(raw: unknown, viewerDid: string | null): Suggestion[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((a): a is Suggestion => !!a && typeof a.agent_did === "string")
    .filter((a) => a.agent_did !== viewerDid)
    .slice(0, MAX_SUGGESTIONS);
}

/** `@handle` when the agent has one, else the DID's last part. */
export function suggestionSubtitle(a: Pick<Suggestion, "agent_did" | "handle">): string {
  if (a.handle) return `@${a.handle}`;
  const parts = a.agent_did.split(":");
  return parts[parts.length - 1] || a.agent_did;
}
