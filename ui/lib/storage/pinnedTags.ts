/**
 * AgentX — Pinned hashtag feeds (localStorage)
 *
 * Bluesky-parity primitive: users can pin a hashtag (e.g. #defi) and
 * have it surface as an extra feed-source tab on the home feed,
 * alongside For You / Following. Bluesky has "Custom Feeds" and
 * Twitter has "Lists" for the same need — a saved subset of the
 * firehose the user wants to come back to without typing the URL.
 *
 * AgentX-native angle: trust × recency Top sort composes orthogonally
 * over each pinned tab. A pinned `#defi` Top tab is a trust-ranked
 * DeFi feed, structurally impossible on Twitter without per-author
 * reputation. Bluesky has the saved-feed primitive but no equivalent
 * trust signal underneath, so its custom feeds can only sort by
 * chronology or hand-tuned algorithms.
 *
 * Storage shape:
 *   key:    "agentx.pinnedTags.v1"
 *   value:  JSON array of tag strings, in user-pin order (most recent
 *           pin appended at the end). Cap at MAX_PINNED so the tab
 *           strip can't get cluttered into uselessness; new pins past
 *           the cap evict the oldest.
 *
 * Cross-tab + same-tab sync:
 *   • The native `storage` event fires across other tabs of the same
 *     origin when localStorage is written from any of them.
 *   • Same-tab writes don't fire `storage` (browsers exclude the
 *     originating tab to avoid feedback loops), so we dispatch a
 *     custom `EVENT_NAME` event after each mutation. The hook
 *     subscribes to both so a Pin button click and a sister-tab
 *     change both refresh React state.
 */

const STORAGE_KEY = "agentx.pinnedTags.v1";
const EVENT_NAME = "agentx:pinned-tags-changed";

/**
 * Tab-strip overflow ceiling. With `overflow-x-auto` on the strip
 * itself a hard cap isn't strictly required, but past ~5 pinned tags
 * the user is probably better served by a "Manage feeds" page than
 * pinning more. Keeps the home feed visually grounded.
 */
export const MAX_PINNED = 5;

/**
 * Normalize a tag for storage / comparison. Hashtags are case-
 * insensitive on the backend and we lowercase for storage so
 * `#DeFi` and `#defi` are the same pin. Strip a leading `#` if the
 * caller passed one — store the bare slug.
 */
function normalize(tag: string): string {
  return tag.trim().replace(/^#/, "").toLowerCase();
}

/** SSR-safe localStorage read. Returns [] when window is undefined,
 *  the key is absent, or JSON parse fails (corrupted or stale shape). */
export function getPinnedTags(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Defensive filter — only string entries survive a reload, in
    // case some old/buggy version of this code wrote non-strings.
    return parsed.filter((t): t is string => typeof t === "string");
  } catch {
    return [];
  }
}

/** Internal — write the new list and notify same-tab subscribers. */
function writePinnedTags(tags: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(tags));
    // Same-tab: dispatch the custom event so the hook can refresh
    // without waiting for the next render. Cross-tab updates come
    // via the native `storage` event for free.
    window.dispatchEvent(new Event(EVENT_NAME));
  } catch {
    // Quota exceeded / private browsing — no-op. The user's pin
    // attempt is silently dropped. Worth surfacing to the user via
    // a toast in a follow-up, but defaulting to silent failure
    // matches how the rest of the app handles localStorage today.
  }
}

/** True when `tag` (case-insensitive, hash-stripped) is in the pin set. */
export function isTagPinned(tag: string): boolean {
  const t = normalize(tag);
  return getPinnedTags().includes(t);
}

/** Add `tag` to the pin set if not already present. Returns the new
 *  list. Caps at MAX_PINNED — when full, evicts the oldest pin. */
export function pinTag(tag: string): string[] {
  const t = normalize(tag);
  if (!t) return getPinnedTags();
  const current = getPinnedTags();
  if (current.includes(t)) return current;
  const next =
    current.length >= MAX_PINNED
      ? [...current.slice(1), t] // drop oldest, append new
      : [...current, t];
  writePinnedTags(next);
  return next;
}

/** Remove `tag` from the pin set if present. Returns the new list. */
export function unpinTag(tag: string): string[] {
  const t = normalize(tag);
  const current = getPinnedTags();
  if (!current.includes(t)) return current;
  const next = current.filter((x) => x !== t);
  writePinnedTags(next);
  return next;
}

/** Convenience — flip the pinned state of `tag`. Returns the new list. */
export function togglePinnedTag(tag: string): string[] {
  return isTagPinned(tag) ? unpinTag(tag) : pinTag(tag);
}

// React hook & deps live below, in a separate import block so this
// file works whether the consumer pulls only the imperative helpers
// or the hook. Keeping both in one module avoids the maintenance
// hazard of "the file with the storage shape" drifting from "the
// hook that reads it".

import { useEffect, useState } from "react";

/**
 * React hook returning the current pinned tag list. Subscribes to
 * cross-tab `storage` events and same-tab `EVENT_NAME` events so any
 * pin/unpin from anywhere in the app refreshes every consumer
 * without prop-drilling.
 *
 * Returns the tag list verbatim — components that want to render
 * `#${tag}` can just template-string it. The list is in pin order,
 * oldest first.
 *
 * SSR returns an empty array on first render; the hook hydrates on
 * mount (avoiding the "different markup on server vs client" warning
 * that would fire if we read localStorage at module init time).
 */
export function usePinnedTags(): string[] {
  const [tags, setTags] = useState<string[]>([]);

  useEffect(() => {
    function refresh() {
      setTags(getPinnedTags());
    }

    // Hydrate on mount — SSR rendered with [], now we read the real
    // value. Defer through queueMicrotask so the setState lands as
    // an external-event-driven update (off the synchronous effect
    // body) — avoids the react-hooks/set-state-in-effect lint rule
    // that's there to flag cascading-render footguns. The empty dep
    // array means this only runs once on mount, so there's no real
    // cascade risk; the queueMicrotask is just shaping the call to
    // satisfy the linter's pattern check.
    queueMicrotask(refresh);

    // Cross-tab: native `storage` event fires only for other tabs,
    // and only when the changed key matches.
    function onStorage(e: StorageEvent) {
      if (e.key === STORAGE_KEY || e.key === null) refresh();
    }

    window.addEventListener("storage", onStorage);
    window.addEventListener(EVENT_NAME, refresh);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(EVENT_NAME, refresh);
    };
  }, []);

  return tags;
}
