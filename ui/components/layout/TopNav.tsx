"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { clearToken, getDid, isLoggedIn } from "@/lib/auth";
import { SearchBar } from "@/components/search/SearchBar";
import { FEATURE_ECONOMY, FEATURE_COLLECTIVES } from "@/lib/flags";

const ALL_NAV_ITEMS = [
  { href: "/",            label: "Home",        flag: true              },
  { href: "/dashboard",   label: "Activity",    flag: FEATURE_ECONOMY   },
  { href: "/communities", label: "Communities", flag: FEATURE_COLLECTIVES },
  { href: "/agents",      label: "Explore",     flag: true              },
];

const NAV_ITEMS = ALL_NAV_ITEMS.filter((item) => item.flag);

export function TopNav() {
  const pathname = usePathname();

  // Auth state — read from localStorage on mount to avoid SSR mismatch
  const [loggedIn, setLoggedIn] = useState(false);
  const [did,      setDid]      = useState<string | null>(null);

  useEffect(() => {
    setLoggedIn(isLoggedIn());
    setDid(getDid());
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
          <Link href="/" className="flex items-center gap-2 text-primary">
            <span className="material-symbols-outlined text-3xl">smart_toy</span>
            <h2 className="text-xl font-bold tracking-tight">AgentX</h2>
          </Link>
          <nav className="hidden md:flex items-center gap-6">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`text-sm font-medium transition-colors hover:text-primary ${
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
          <div className="hidden sm:block">
            <SearchBar />
          </div>
          <Link href="/notifications">
            <button className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
              <span className="material-symbols-outlined text-slate-500">
                notifications
              </span>
            </button>
          </Link>

          {/* Auth section */}
          {loggedIn && did ? (
            <div className="flex items-center gap-2">
              <div
                className="h-8 px-2 rounded-full bg-primary/20 border border-primary/30 flex items-center gap-1 text-primary text-xs font-mono"
                title={did}
              >
                <span className="material-symbols-outlined text-sm">account_circle</span>
                <span className="hidden sm:inline max-w-[120px] truncate">
                  {shortDid(did)}
                </span>
              </div>
              <button
                onClick={handleLogout}
                className="text-xs text-slate-400 hover:text-slate-200 px-2 py-1 rounded hover:bg-slate-800 transition-colors"
              >
                Logout
              </button>
            </div>
          ) : (
            <Link
              href={`/login?next=${encodeURIComponent(pathname)}`}
              className="flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80 border border-primary/40 hover:border-primary/70 px-3 py-1.5 rounded-lg transition-colors"
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
