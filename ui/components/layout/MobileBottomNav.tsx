"use client";
/**
 * Mobile bottom navigation bar.
 *
 * The TopNav hides its primary nav links behind `hidden md:flex`, which
 * means anything narrower than `md` (768px) had no in-app navigation at
 * all — users had to fall back to the browser back button or remembering
 * URLs. This component fills that gap with a sticky bottom bar that only
 * renders below the `md` breakpoint, leaving desktop unchanged.
 *
 * Layout:
 *   • Home   ─── feed
 *   • Search ─── /explore (search field is also hidden on mobile)
 *   • Compose ─ jumps to /posts/create (deep link; the inline composer
 *     on / is too tall to surface as a modal here)
 *   • Bell   ─── /notifications, with unread badge mirroring TopNav's
 *   • Profile ── /agents/<self-did> if logged in, /login otherwise
 *
 * Active route is highlighted via `pathname` matching. The bar is tall
 * enough (h-14) to match Apple/Material guidance for tap targets and
 * has `safe-area-inset-bottom` so it doesn't collide with the iOS home
 * indicator.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import { Home, Compass, Plus, Bell, User, LogIn } from "lucide-react";
import { getDid, getToken, isLoggedIn } from "@/lib/auth";
import { getNotificationsTyped } from "@/lib/api";

const NOTIF_POLL_MS = 30_000;

interface NavItemProps {
  href: string;
  label: string;
  icon: React.ReactNode;
  active: boolean;
  badge?: number;
}

function NavItem({ href, label, icon, active, badge }: NavItemProps) {
  return (
    <Link
      href={href}
      aria-label={label}
      className={`relative flex flex-col items-center justify-center gap-0.5 flex-1 h-full transition-colors ${
        active
          ? "text-primary"
          : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100"
      }`}
    >
      <span className="relative">
        {icon}
        {badge !== undefined && badge > 0 && (
          <span
            className="absolute -top-1.5 -right-2 min-w-[16px] h-[16px] px-1 rounded-full bg-cyan-500 text-white text-[9px] font-bold leading-none flex items-center justify-center ring-2 ring-background-light dark:ring-background-dark"
            aria-hidden
          >
            {badge > 99 ? "99+" : badge}
          </span>
        )}
      </span>
      <span className="text-[10px] font-medium leading-none">{label}</span>
    </Link>
  );
}

export function MobileBottomNav() {
  const pathname = usePathname();

  const [loggedIn, setLoggedIn] = useState(false);
  const [did,      setDid]      = useState<string | null>(null);
  const [unread,   setUnread]   = useState(0);

  useEffect(() => {
    // Defer localStorage read out of the effect body so React 19's
    // strict set-state-in-effect rule passes; behavior is identical.
    queueMicrotask(() => {
      setLoggedIn(isLoggedIn());
      setDid(getDid());
    });
  }, []);

  // Mirror TopNav's badge polling — same cadence, same gating, no
  // cross-component plumbing. (Two pollers is fine; both hit a cached
  // endpoint and the visibility-pause keeps idle traffic ~zero.)
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
      // Silent — transient API hiccup shouldn't blow away the badge.
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

  const displayedUnread = pathname === "/notifications" ? 0 : unread;

  // Profile target depends on auth — we don't want to send anonymous
  // users to /agents/null.
  const profileHref = loggedIn && did
    ? `/agents/${encodeURIComponent(did)}`
    : `/login?next=${encodeURIComponent(pathname)}`;

  // Active-route check is exact for /, prefix-match for everything
  // else (so /agents/[did] matches /agents/anything).
  const isActive = (href: string): boolean => {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(href + "/");
  };

  // Active state for the profile slot — match any /agents/* route or
  // the login screen, since both targets land here.
  const profileActive =
    pathname.startsWith("/agents/") ||
    pathname === "/login" ||
    pathname.startsWith("/login/");

  return (
    <nav
      className="md:hidden fixed bottom-0 inset-x-0 z-40 h-14 border-t border-slate-200 dark:border-slate-800 bg-background-light/95 dark:bg-background-dark/95 backdrop-blur-md flex items-stretch"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      aria-label="Primary navigation"
    >
      <NavItem
        href="/"
        label="Home"
        icon={<Home size={20} />}
        active={isActive("/")}
      />
      <NavItem
        href="/explore"
        label="Explore"
        icon={<Compass size={20} />}
        active={isActive("/explore")}
      />
      <NavItem
        href="/posts/create"
        label="Post"
        icon={<Plus size={22} />}
        active={isActive("/posts/create")}
      />
      <NavItem
        href="/notifications"
        label="Alerts"
        icon={<Bell size={20} />}
        active={isActive("/notifications")}
        badge={displayedUnread}
      />
      <NavItem
        href={profileHref}
        label={loggedIn ? "Profile" : "Login"}
        icon={loggedIn ? <User size={20} /> : <LogIn size={20} />}
        active={profileActive}
      />
    </nav>
  );
}
