"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { clearToken, getDid, isLoggedIn } from "@/lib/auth";
import { SearchBar } from "@/components/search/SearchBar";
import { NotificationBell } from "@/components/layout/NotificationBell";
import { FEATURE_ECONOMY, FEATURE_COLLECTIVES } from "@/lib/flags";

// (Notification poll cadence + dropdown logic moved into
//  components/layout/NotificationBell.tsx.)

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

  useEffect(() => {
    // Microtask defers the localStorage read out of the effect body so
    // React 19's set-state-in-effect rule passes; behaviour is identical
    // (still runs once on mount, before any user interaction).
    queueMicrotask(() => {
      setLoggedIn(isLoggedIn());
      setDid(getDid());
    });
  }, []);

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
          {/* Bell + dropdown preview. The component owns the
              unread-count poll, popover state, and click-outside /
              Escape handlers; TopNav just hands it the auth flag. */}
          <NotificationBell loggedIn={loggedIn} />

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
