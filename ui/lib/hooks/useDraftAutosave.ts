"use client";

/**
 * AgentX — useDraftAutosave
 *
 * Persists compose-box state to localStorage so a closed tab / accidental
 * navigation / OS restart doesn't lose what the user typed. The hook is
 * deliberately decoupled from any specific composer — pass in a stable
 * key and the field values you want preserved, plus an `onHydrate`
 * callback that re-applies a saved draft to your own useState setters.
 *
 * Behaviour:
 *   • On mount: read localStorage[key]; if present and within TTL, fire
 *     onHydrate(savedValues). Older entries are evicted.
 *   • On every values change: debounced (500 ms) save back to
 *     localStorage as {ts, values}. Empty drafts are cleared rather than
 *     stored.
 *   • clear(): wipes the entry. Composers should call this on successful
 *     submit so the cleared form doesn't immediately re-save the blank.
 *
 * Storage shape: { ts: number, values: Record<string, string> }
 * Failures (quota, parse error, SSR window-undef) are swallowed — drafts
 * are best-effort, not a guarantee.
 */
import { useEffect, useRef, useState } from "react";

export interface DraftFields {
  [field: string]: string;
}

interface Options {
  /** Stable storage key — e.g. `agentx:draft:root` or `agentx:draft:reply:${parentPostId}`. */
  key:       string;
  /** Current values. Hook saves these debounced when they change. */
  values:    DraftFields;
  /** Called once on mount if a saved draft exists, with the saved values. */
  onHydrate: (saved: DraftFields) => void;
  /** TTL in ms; older entries are evicted on load. Default 7 days. */
  ttlMs?:    number;
}

const DEFAULT_TTL_MS = 7 * 24 * 60 * 60 * 1000;

function isAllEmpty(values: DraftFields): boolean {
  return Object.values(values).every((v) => !v || !v.trim());
}

export function useDraftAutosave({
  key,
  values,
  onHydrate,
  ttlMs = DEFAULT_TTL_MS,
}: Options) {
  // Tracks whether we've ever successfully written this key in this mount —
  // drives the "Draft saved" indicator. Lives in a ref so the save effect
  // can read+write it without re-running.
  const [didSave, setDidSave] = useState(false);
  const hydratedRef = useRef(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Hydrate once on mount.
  useEffect(() => {
    if (hydratedRef.current) return;
    hydratedRef.current = true;
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(key);
      if (!raw) return;
      const parsed = JSON.parse(raw) as { ts?: number; values?: DraftFields };
      if (!parsed?.ts || !parsed.values) return;
      if (Date.now() - parsed.ts > ttlMs) {
        window.localStorage.removeItem(key);
        return;
      }
      onHydrate(parsed.values);
    } catch {
      // Corrupted entry — drop it.
      try { window.localStorage.removeItem(key); } catch { /* noop */ }
    }
    // Hydration is intentionally one-shot: changing the key mid-session
    // (e.g. from root → reply) is not a supported flow because each
    // composer instance gets its own hook instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Debounced save on values change.
  useEffect(() => {
    if (!hydratedRef.current) return;
    if (typeof window === "undefined") return;

    if (isAllEmpty(values)) {
      // Empty draft → remove from storage so we don't resurrect a stale
      // draft on the next mount. Don't touch didSave here (keep "saved"
      // indicator only while the user has content).
      try { window.localStorage.removeItem(key); } catch { /* noop */ }
      return;
    }

    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      try {
        window.localStorage.setItem(
          key,
          JSON.stringify({ ts: Date.now(), values }),
        );
        // setState inside setTimeout is async w.r.t. the effect body, so
        // it doesn't trip React 19's "no setState directly in effect" rule.
        setDidSave(true);
      } catch {
        // Quota exceeded or storage disabled — drafts are best-effort.
      }
    }, 500);

    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [key, values]);

  function clear() {
    if (typeof window !== "undefined") {
      try { window.localStorage.removeItem(key); } catch { /* noop */ }
    }
    setDidSave(false);
  }

  return { didSave, clear };
}
