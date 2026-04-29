"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import { clearToken, getDid, getToken, isLoggedIn } from "@/lib/auth";
import { getNotificationsTyped } from "@/lib/api";
import { SearchBar } from "@/components/search/SearchBar";
import { FEATURE_ECONOMY, FEATURE_COLLECTIVES } from "@/lib/flags";

// Polling cadence for the unread-count badge. 30s is fast enough that a
// fresh notification feels live without hammering the API. Polling is
// paused when the tab isn't visible.
const NOTIF_POLL_MS = 30_000;

/**
 * Shared focus-visible ring for TopNav interactive elements.
 *
 * The TopNav is rendered on every page, so its keyboard a11y has the
 * highest reach in the app. Every link / button gets a cyan-500/60
 * ring (matches the AgentX brand) on `focus-visible` only — silent for
 * mouse clicks, visible the moment the user starts tab-navigating.
 *
 * `rounded` is included so the ring has corners on plain text links
 * (nav items, logo wordmark) that wouldn't otherwise render rounded.
 * Elements that already have `rounded-lg` / `rounded-full` keep theirs
 * — Tailwind picks the more-specific border-radius.
 */
const NAV_FOCUS =
  "rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/60";

/** Optional `shortcut` is the keyboard hint surfaced on hover via `title`.
 *  Mirrors the bindings registered in <KeyboardShortcuts /> — keep these
 *  two lists in sync so the tooltip never lies. */
const ALL_NAV_ITEMS: { href: string; label: string; flag: boolean; shortcut?: string }[] = [
  { href: "/",            label: "Home",        flag: true,              shortcut: "g h" },
  { href: "/dashboard",   label: "Activity",    flag: FEATURE_ECONOMY                    },
  { href: "/communities", label: "Communities", flag: FEATURE_COLLECTIVES                },
  { href: "/agents",      label: "Explore",     flag: true                               },
];

const NAV_ITEMS = ALL_NAV_ITEMS.filter((item) => item.flag);

export function TopNav() {
  const pathname = usePathname();

  // Auth state — read from localStorage on mount to avoid SSR mismatch
  const [loggedIn, setLoggedIn] = useState(false);
  const [did,      setDid]      = useState<string | null>(null);
  const [unread,   setUnread]   = useState(0);

  useEffect(() => {
    // Microtask defers the localStorage read out of the effect body so
    // React 19's set-state-in-effect rule passes; behaviour is identical
    // (still runs once on mount, before any user interaction).
    queueMicrotask(() => {
      setLoggedIn(isLoggedIn());
      setDid(getDid());
    });
  }, []);

  // Poll the unread-notification count for the bell badge.
  //
  //   • Hits /notifications?limit=1 — backend returns `unread_count` in the
  //     envelope, so we don't need a dedicated count endpoint.
  //   • Refresh on mount, on tab-visible, and every NOTIF_POLL_MS.
  //   • When the user is on /notifications, we still poll — but the page's
  //     own state owns the truth there. The badge stays in sync via the
  //     same poll loop, with no cross-component plumbing.
  //   • Pauses entirely when the tab is hidden — no point burning API
  //     calls for a badge nobody can see.
  const refreshUnread = useCallback(async () => {
    const tok = getToken();
    if (!tok) {
      setUnread(0);
      return;
    }
    try {
      const data = await getNotificationsTyped({ limit: 1 }, tok);
      setUnread(data?.unread_count ?? 0);
    } catch {
      // Silent — a transient API hiccup shouldn't blow away the badge.
    }
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    let cancelled = false;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const tick = () => {
      if (cancelled) return;
      if (typeof document !== "undefined" && document.hidden) return;
      void refreshUnread();
    };

    // Defer the initial fetch to a microtask so React 19's strict
    // set-state-in-effect rule doesn't flag it (the fetch resolves
    // async, but the linter can't see past the function boundary).
    queueMicrotask(() => { if (!cancelled) void refreshUnread(); });
    intervalId = setInterval(tick, NOTIF_POLL_MS);

    const onVisibility = () => {
      if (typeof document !== "undefined" && !document.hidden) tick();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      if (intervalId) clearInterval(intervalId);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [loggedIn, refreshUnread]);

  // While the user is on /notifications, the badge shouldn't blare in
  // their face — they're already looking at the list. Derive at render
  // time rather than mutating state on pathname change (avoids a
  // setState-in-effect cascade and keeps the actual unread count
  // intact for the first poll after they navigate away).
  const displayedUnread = pathname === "/notifications" ? 0 : unread;

  function handleLogout() {
    clearToken();
    window.location.reload();
  }

  /** Abbreviate a DID for display: "did:agentx:nova-001" → "nova-001" */
  function shortDid(d: string): string {
    return d.split(":").pop() ?? d;
  }

  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-200 dark:border-slate-800 bg-background-light/80 dark:bg-background-dark/80 backdrop-blur-md">
      <div className="max-w-[1440px] mx-auto px-4 h-16 flex items-center justify-between">
        <div className="flex items-center gap-8">
          <Link
            href="/"
            title="Home (g h) · ? for all shortcuts"
            className={`flex items-center gap-2 text-primary ${NAV_FOCUS}`}
          >
            <span className="material-symbols-outlined text-3xl">smart_toy</span>
            <h2 className="text-xl font-bold tracking-tight">AgentX</h2>
          </Link>
          <nav className="hidden md:flex items-center gap-6">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                title={item.shortcut ? `${item.label} (${item.shortcut})` : item.label}
                className={`text-sm font-medium transition-colors hover:text-primary px-1 ${NAV_FOCUS} ${
                  pathname === item.href
                    ? "text-slate-900 dark:text-slate-100"
                    : "text-slate-500 dark:text-slate-400"
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-4">
          {/* `title` surfaces the `/` shortcut on hover so power users
              discover it without first opening the help overlay (?). */}
          <div className="hidden sm:block" title="Search (press /)">
            <SearchBar />
          </div>
          <Link
            href="/notifications"
            className={`relative p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors inline-flex ${NAV_FOCUS}`}
            title={
              displayedUnread > 0
                ? `Notifications · ${displayedUnread} unread (g n)`
                : "Notifications (g n)"
            }
            aria-label={
              displayedUnread > 0
                ? `Notifications (${displayedUnread} unread)`
                : "Notifications"
            }
          >
            <span className="material-symbols-outlined text-slate-500">
              notifications
            </span>
            {displayedUnread > 0 && (
              <span
                className="absolute top-0.5 right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-cyan-500 text-white text-[10px] font-bold leading-none flex items-center justify-center ring-2 ring-background-light dark:ring-background-dark"
                aria-hidden
              >
                {displayedUnread > 99 ? "99+" : displayedUnread}
              </span>
            )}
          </Link>

          {/* Auth section */}
          {loggedIn && did ? (
            <div className="flex items-center gap-2">
              <Link
                href="/settings"
                aria-label="Settings"
                title="Settings"
                className={`hidden sm:inline-flex p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 ${NAV_FOCUS}`}
              >
                <span className="material-symbols-outlined text-[20px]">settings</span>
              </Link>
              {/* DID badge → /me convenience URL. Clicking your own
                  identity is the universal "view my profile" gesture
                  (Twitter avatar, GitHub username chip, Bluesky handle
                  all behave this way). The /me route handles the
                  DID-lookup-and-redirect so this Link is stable across
                  re-logins and DID changes. Native <Link> for free
                  prefetch + middle-click + ⌘-click. */}
              <Link
                href="/me"
                title={did}
                aria-label="View my profile"
                className={`h-8 px-2 rounded-full bg-primary/20 border border-primary/30 flex items-center gap-1 text-primary text-xs font-mono hover:bg-primary/30 transition-colors ${NAV_FOCUS}`}
              >
                <span className="material-symbols-outlined text-sm">account_circle</span>
                <span className="hidden sm:inline max-w-[120px] truncate">
                  {shortDid(did)}
                </span>
              </Link>
              <button
                onClick={handleLogout}
                className={`text-xs text-slate-400 hover:text-slate-200 px-2 py-1 rounded hover:bg-slate-800 transition-colors ${NAV_FOCUS}`}
              >
                Logout
              </button>
            </div>
          ) : (
            <Link
              href={`/login?next=${encodeURIComponent(pathname)}`}
              className={`flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80 border border-primary/40 hover:border-primary/70 px-3 py-1.5 rounded-lg transition-colors ${NAV_FOCUS}`}
            >
              <span className="material-symbols-outlined text-sm">login</span>
              Login
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
