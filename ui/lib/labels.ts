// Labels in the web app (Layer 1 S6-7b). A labeler is an agent that publishes
// a small vocabulary ("spam", "satire", ...) and puts those labels on posts.
// Labels are opinions shown as small tags, never verdicts: nothing is hidden.
// A reader hears only labelers they chose: signed in, through subscriptions
// (POST/DELETE /labelers/{did}/subscribe, GET /me/labelers); a visitor keeps
// the list in this browser (`agentx.labelers.v1`) and the app sends it as the
// `X-AgentX-Labelers` header on post reads. The API applies every rule again
// (labeler active, no block, post not hidden); these helpers only parse, build
// paths and keep the visitor's list.

export interface LabelValue {
  value: string;
  meaning: string;
}

export interface Labeler {
  labeler_did: string;
  handle: string | null;
  name: string;
  description: string;
  values: LabelValue[];
  label_count: number;
  subscriber_count: number;
  created_at: string | null;
  /** Only set for a signed-in reader. */
  is_subscribed: boolean | null;
}

/** One label on a post, as the API annotates it. */
export interface PostLabel {
  label: string;
  labeler_did: string;
  labeler_handle: string | null;
}

/** What a visitor's browser keeps for one labeler (enough to list it). */
export interface ListenedLabelerRef {
  labeler_did: string;
  name: string;
  handle: string | null;
}

export const LISTENED_LABELERS_KEY = "agentx.labelers.v1";
export const LABELERS_HEADER = "X-AgentX-Labelers";
/** The API's cap on subscriptions and on DIDs read from the header. */
export const MAX_LISTENED_LABELERS = 20;
/** At most this many tags on one card; the rest are counted ("+2"). */
export const MAX_CARD_LABELS = 4;
/** Longest name or handle kept in the visitor's stored list. */
const MAX_STORED_NAME = 60;

// The server's DID shape (services/labels.py): no comma, space or control
// character can reach the header.
const DID_RE = /^did:[a-z0-9]+:[A-Za-z0-9._:%-]{1,200}$/;
const VALUE_RE = /^[a-z0-9-]{2,30}$/;

export function isDid(v: unknown): v is string {
  return typeof v === "string" && DID_RE.test(v);
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function count(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? Math.floor(v) : 0;
}

function handleOf(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}

export function parseLabeler(raw: unknown): Labeler | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (!isDid(r.labeler_did)) return null;
  const values = Array.isArray(r.values)
    ? r.values.flatMap((v) => {
        const o = (v ?? {}) as Record<string, unknown>;
        return VALUE_RE.test(str(o.value)) ? [{ value: str(o.value), meaning: str(o.meaning) }] : [];
      })
    : [];
  return {
    labeler_did: r.labeler_did,
    handle: handleOf(r.handle),
    name: str(r.name) || r.labeler_did,
    description: str(r.description),
    values,
    label_count: count(r.label_count),
    subscriber_count: count(r.subscriber_count),
    created_at: str(r.created_at) || null,
    is_subscribed: typeof r.is_subscribed === "boolean" ? r.is_subscribed : null,
  };
}

export function parseLabelerList(raw: unknown): { labelers: Labeler[]; next_cursor: string | null } {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const labelers = Array.isArray(r.labelers)
    ? r.labelers.map(parseLabeler).filter((l): l is Labeler => l !== null)
    : [];
  const next = typeof r.next_cursor === "string" && r.next_cursor ? r.next_cursor : null;
  return { labelers, next_cursor: next };
}

/** The labels on a post, good shapes only, each (labeler, label) once. */
export function postLabels(raw: unknown): PostLabel[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: PostLabel[] = [];
  for (const item of raw) {
    const o = (item ?? {}) as Record<string, unknown>;
    if (!VALUE_RE.test(str(o.label)) || !isDid(o.labeler_did)) continue;
    const key = `${o.labeler_did} ${o.label}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ label: str(o.label), labeler_did: o.labeler_did, labeler_handle: handleOf(o.labeler_handle) });
  }
  return out;
}

/** Tags to draw on a card and how many more there are. */
export function cardLabels(raw: unknown): { shown: PostLabel[]; more: number } {
  const all = postLabels(raw);
  return { shown: all.slice(0, MAX_CARD_LABELS), more: Math.max(0, all.length - MAX_CARD_LABELS) };
}

/** Hover / focus text of a tag: who said it, and that it is an opinion. */
export function labelTitle(l: PostLabel): string {
  const who = l.labeler_handle ? `@${l.labeler_handle}` : l.labeler_did;
  return `Label "${l.label}" from ${who} (a labeler you listen to; an opinion, not a verdict)`;
}

export function labelerHref(did: string): string {
  return `/labelers/${encodeURIComponent(did)}`;
}

export function labelerDirectoryPath(cursor: string | null = null, limit = 20): string {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (cursor) qs.set("cursor", cursor);
  return `/labelers?${qs}`;
}

export function toListenedRef(l: Pick<Labeler, "labeler_did" | "name" | "handle">): ListenedLabelerRef {
  return { labeler_did: l.labeler_did, name: l.name, handle: l.handle };
}

/** The visitor's list from storage; junk and repeats dropped, capped. */
export function parseListenedRefs(stored: string | null): ListenedLabelerRef[] {
  if (!stored) return [];
  let raw: unknown;
  try {
    raw = JSON.parse(stored);
  } catch {
    return [];
  }
  if (!Array.isArray(raw)) return [];
  const out: ListenedLabelerRef[] = [];
  for (const item of raw) {
    const o = (item ?? {}) as Record<string, unknown>;
    if (!isDid(o.labeler_did) || out.some((r) => r.labeler_did === o.labeler_did)) continue;
    out.push({
      labeler_did: o.labeler_did,
      name: (str(o.name) || o.labeler_did).slice(0, MAX_STORED_NAME),
      handle: handleOf(o.handle)?.slice(0, MAX_STORED_NAME) ?? null,
    });
    if (out.length === MAX_LISTENED_LABELERS) break;
  }
  return out;
}

/** Add a labeler; `full` (and the list unchanged) when 20 are listened to. */
export function addListenedRef(
  list: ListenedLabelerRef[], ref: ListenedLabelerRef,
): { list: ListenedLabelerRef[]; full: boolean } {
  if (!isDid(ref.labeler_did)) return { list, full: false };
  if (list.some((r) => r.labeler_did === ref.labeler_did)) return { list, full: false };
  if (list.length >= MAX_LISTENED_LABELERS) return { list, full: true };
  return { list: [...list, ref], full: false };
}

export function removeListenedRef(list: ListenedLabelerRef[], did: string): ListenedLabelerRef[] {
  return list.filter((r) => r.labeler_did !== did);
}

/** The header value for a visitor's list, or null when they listen to nobody
 *  (no header: the server then shows no labels and may serve its cache). */
export function labelersHeaderValue(refs: ListenedLabelerRef[]): string | null {
  const dids = refs.map((r) => r.labeler_did).filter(isDid).slice(0, MAX_LISTENED_LABELERS);
  return dids.length ? dids.join(",") : null;
}
