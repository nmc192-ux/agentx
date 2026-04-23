"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

const STORAGE_KEY = "agentx.cookie-consent";

type Consent = "necessary" | "all" | null;

/**
 * Lightweight cookie-consent banner.
 *
 * Default position is "necessary only" — we do not set marketing or analytics
 * cookies, and the only functional storage we use is a JWT in localStorage to
 * keep the user logged in. The banner therefore acts as a disclosure +
 * opt-in for any future analytics, not a gate on core site functionality.
 *
 * State lives in localStorage under `agentx.cookie-consent`. Reading that
 * key elsewhere tells other components whether analytics may be initialised.
 */
export function CookieBanner() {
  const [visible, setVisible] = useState(false);

  // Client-only mount check — we can't read localStorage during SSR, so the
  // banner starts hidden and shows after we confirm there's no prior consent.
  // setState-in-effect is intentional here; this is a one-shot mount read.
  useEffect(() => {
    try {
      const existing = window.localStorage.getItem(STORAGE_KEY) as Consent;
      if (!existing) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setVisible(true);
      }
    } catch {
      // localStorage unavailable (e.g. privacy mode) — do not show.
    }
  }, []);

  function save(choice: Exclude<Consent, null>) {
    try {
      window.localStorage.setItem(STORAGE_KEY, choice);
    } catch {
      // noop
    }
    setVisible(false);
  }

  if (!visible) return null;

  return (
    <div
      role="dialog"
      aria-label="Cookie consent"
      className="fixed inset-x-0 bottom-0 z-[60] border-t border-slate-200 dark:border-slate-800 bg-background-light/95 dark:bg-background-dark/95 backdrop-blur-md shadow-lg"
    >
      <div className="max-w-[1440px] mx-auto px-4 py-4 flex flex-col md:flex-row items-start md:items-center gap-3 md:gap-6">
        <p className="text-sm text-slate-700 dark:text-slate-300 flex-1">
          AgentX stores a single JWT in your browser to keep you logged in —
          no ad trackers, no cross-site profiling. See our{" "}
          <Link href="/privacy" className="text-primary hover:underline">
            Privacy Policy
          </Link>{" "}
          for details.
        </p>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => save("necessary")}
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            Necessary only
          </button>
          <button
            onClick={() => save("all")}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-primary text-white hover:bg-primary/90 transition-colors"
          >
            Accept all
          </button>
        </div>
      </div>
    </div>
  );
}
