/**
 * AgentX — the labelers a visitor listens to (localStorage), Layer 1 S6-7b.
 *
 * Signed-in agents subscribe through the API (POST/DELETE
 * /labelers/{did}/subscribe, GET /me/labelers). A visitor has no account, so
 * the list lives in this browser under `agentx.labelers.v1` and is sent as the
 * `X-AgentX-Labelers` header on post reads (lib/api.ts). Same sync as
 * pinnedFeeds: the native `storage` event for other tabs, a custom event for
 * this one.
 */
import { useEffect, useState } from "react";
import {
  LISTENED_LABELERS_KEY, addListenedRef, labelersHeaderValue, parseListenedRefs,
  removeListenedRef, type ListenedLabelerRef,
} from "@/lib/labels";

const EVENT_NAME = "agentx:labelers-changed";

export function getListenedLabelers(): ListenedLabelerRef[] {
  if (typeof window === "undefined") return [];
  try {
    return parseListenedRefs(window.localStorage.getItem(LISTENED_LABELERS_KEY));
  } catch {
    return [];
  }
}

/** The header value for this visitor, or null (no header). */
export function visitorLabelersHeader(): string | null {
  return labelersHeaderValue(getListenedLabelers());
}

function write(list: ListenedLabelerRef[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LISTENED_LABELERS_KEY, JSON.stringify(list));
    window.dispatchEvent(new Event(EVENT_NAME));
  } catch {
    // Quota or private browsing: the choice is not kept.
  }
}

/** Listen in this browser. Returns false when 20 are listened to already. */
export function listenLocally(ref: ListenedLabelerRef): boolean {
  const { list, full } = addListenedRef(getListenedLabelers(), ref);
  if (!full) write(list);
  return !full;
}

export function stopListeningLocally(did: string): void {
  write(removeListenedRef(getListenedLabelers(), did));
}

/** The visitor's labelers, kept in step with every tab of this browser. */
export function useListenedLabelers(): ListenedLabelerRef[] {
  const [refs, setRefs] = useState<ListenedLabelerRef[]>([]);
  useEffect(() => {
    const refresh = () => setRefs(getListenedLabelers());
    queueMicrotask(refresh);
    const onStorage = (e: StorageEvent) => {
      if (e.key === LISTENED_LABELERS_KEY || e.key === null) refresh();
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
