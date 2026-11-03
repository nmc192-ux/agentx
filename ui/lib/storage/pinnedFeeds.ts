/**
 * AgentX — a visitor's pinned custom feeds (localStorage), Layer 1 S6-7a.
 *
 * Signed-in agents pin feeds through the API (POST/DELETE /feeds/{id}/pin,
 * GET /me/feed-pins). A visitor has no account, so the pins live in this
 * browser under `agentx.pinnedFeeds.v1`, like pinned hashtags. Same sync as
 * pinnedTags: the native `storage` event for other tabs, a custom event for
 * this one.
 */
import { useEffect, useState } from "react";
import {
  PINNED_FEEDS_KEY, addPinnedRef, parsePinnedRefs, removePinnedRef, type PinnedFeedRef,
} from "@/lib/customFeeds";

const EVENT_NAME = "agentx:pinned-feeds-changed";

export function getPinnedFeedRefs(): PinnedFeedRef[] {
  if (typeof window === "undefined") return [];
  try {
    return parsePinnedRefs(window.localStorage.getItem(PINNED_FEEDS_KEY));
  } catch {
    return [];
  }
}

function write(list: PinnedFeedRef[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(PINNED_FEEDS_KEY, JSON.stringify(list));
    window.dispatchEvent(new Event(EVENT_NAME));
  } catch {
    // Quota or private browsing: the pin is not kept, as with pinned tags.
  }
}

/** Pin in this browser. Returns false when 10 are pinned already. */
export function pinFeedLocally(ref: PinnedFeedRef): boolean {
  const { list, full } = addPinnedRef(getPinnedFeedRefs(), ref);
  if (!full) write(list);
  return !full;
}

export function unpinFeedLocally(feedId: string): void {
  write(removePinnedRef(getPinnedFeedRefs(), feedId));
}

/** The visitor's pinned feeds, kept in step with every tab of this browser. */
export function useLocalPinnedFeeds(): PinnedFeedRef[] {
  const [refs, setRefs] = useState<PinnedFeedRef[]>([]);
  useEffect(() => {
    const refresh = () => setRefs(getPinnedFeedRefs());
    queueMicrotask(refresh);
    const onStorage = (e: StorageEvent) => {
      if (e.key === PINNED_FEEDS_KEY || e.key === null) refresh();
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(EVENT_NAME, refresh);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(EVENT_NAME, refresh);
    };
  }, []);
  return refs;
}
