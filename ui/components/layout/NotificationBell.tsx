"use client";

/**
 * AgentX — TopNav Notification Bell + Dropdown Preview
 *
 * The bell in TopNav was a plain `<Link href="/notifications">` —
 * clicking it forced a full route change just to triage the latest
 * five rows. Twitter / Bluesky / Slack / GitHub all expose a popover
 * preview from the bell so users can scan, mark read, and navigate to
 * a single notification without leaving the current page. This drops
 * that pattern onto AgentX.
 *
 * Single component owns:
 *   • The unread-count poll (was inline in TopNav before this ship,
 *     hoisted here so the bell is the single source of truth — no
 *     prop plumbing, no double-poll).
 *   • The popover state (open / closed) with click-outside + Escape +
 *     route-change auto-close.
 *   • Lazy fetch of the preview list on first open via the existing
 *     `getNotificationsTyped({ limit: 5 })` call. We deliberately
 *     don't pre-fetch on mount — the polling already gets the unread
 *     count cheaply, and pre-fetching the bodies on every page would
 *     burn bandwidth for visitors who never open the bell.
 *   • Per-row click behavior matching /notifications page exactly:
 *     mark read, then navigate to `ref_post_id` post or `from_did`
 *     profile.
 *
 * Modifier-click behavior preserved from the original Link: ⌘/Ctrl/
 * middle-click on the bell still navigates to /notifications in a
 * new tab (same pattern used by the followers/following count Links
 * in AgentProfileClient — Next.js Link's native modifier-key
 * navigation continues to work because the onClick guard short-
 * circuits on modifier keys).
 *
 * Visual: matches the SettingsPage hydration shell language and the
 * /notifications page's row treatment, so the preview feels like
 * "the same data, smaller window" rather than a third inbox flavour.
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, CheckCheck, Loader2 } from "lucide-react";
import {
  getNotificationsTyped,
  markAllNotifsRead,
  markNotifRead,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { shortDid, timeAgo } from "@/lib/utils";
import type { Notification } from "@/types";

// Reuse the same poll cadence the inline implementation used so the
// badge behavior is bit-for-bit identical post-extraction.
const NOTIF_POLL_MS = 30_000;
const PREVIEW_LIMIT = 5;

const NAV_FOCUS =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/60";

const NOTIF_ICONS: Record<string, string> = {
  FOLLOW:         "person_add",
  MENTION:        "alternate_email",
  REPLY:          "reply",
  LIKE:           "favorite",
  TASK_ASSIGNED:  "assignment_ind",
  THREAD_REPLY:   "reply",
  COMMUNITY_JOIN: "group_add",
  COMMUNITY_POST: "post_add",
  TRUST_UPDATE:   "verified",
};

function describe(n: Notification): string {
  const who = n.from_name ?? (n.from_did ? shortDid(n.from_did) : "Someone");
  switch (n.notif_type) {
    case "FOLLOW":        return `${who} followed you`;
    case "LIKE":          return `${who} liked your post`;
    case "REPLY":         return `${who} replied to your post`;
    case "MENTION":       return `${who} mentioned you`;
    case "TASK_ASSIGNED": return `${who} assigned you a task`;
    default:              return `${who} · ${n.notif_type}`;
  }
}

interface Props {
  loggedIn: boolean;
}

export function NotificationBell({ loggedIn }: Props) {
  const router   = useRouter();
  const pathname = usePathname();

  const [unread,        setUnread]       = useState(0);
  const [open,          setOpen]         = useState(false);
  const [items,         setItems]        = useState<Notification[]>([]);
  const [previewLoaded, setPreviewLoaded] = useState(false);
  const [loading,       setLoading]      = useState(false);
  const [markingAll,    setMarkingAll]   = useState(false);

  const wrapperRef = useRef<HTMLDivElement>(null);

  // While the user is on /notifications, the badge shouldn't blare in
  // their face — they're already looking at the inbox. Mirrors the
  // pre-extraction logic exactly.
  const displayedUnread = pathname === "/notifications" ? 0 : unread;

  // ── Unread-count poll ───────────────────────────────────────────────
  // Same cadence + visibility guard as before extraction. Pauses while
  // the tab is hidden to avoid burning calls on a badge nobody sees.
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

  // Auto-close the popover on route change so it doesn't linger over
  // the new page.
  useEffect(() => { setOpen(false); }, [pathname]);

  // ── Preview fetch on first open ─────────────────────────────────────
  const loadPreview = useCallback(async () => {
    const tok = getToken();
    if (!tok) return;
    setLoading(true);
    try {
      const data = await getNotificationsTyped({ limit: PREVIEW_LIMIT }, tok);
      setItems(data?.notifications ?? []);
      setUnread(data?.unread_count ?? 0);
      setPreviewLoaded(true);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // ── Click-outside + Escape ──────────────────────────────────────────
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // ── Bell click handler ──────────────────────────────────────────────
  // Plain left-click: open dropdown (and lazy-load preview on first
  // open). Modifier-key click falls through to native Link navigation
  // so power users keep their "open in new tab" workflow.
  function onBellClick(e: React.MouseEvent<HTMLAnchorElement>) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    const next = !open;
    setOpen(next);
    if (next && !previewLoaded && !loading) {
      void loadPreview();
    }
  }

  // ── Per-row click — mirrors /notifications page's handleClick ───────
  async function onRowClick(n: Notification) {
    const tok = getToken();
    if (tok && !n.is_read) {
      try {
        await markNotifRead(n.notif_id, tok);
        setItems((prev) =>
          prev.map((x) => (x.notif_id === n.notif_id ? { ...x, is_read: true } : x)),
        );
        setUnread((c) => Math.max(0, c - 1));
      } catch { /* swallow */ }
    }
    setOpen(false);
    if (n.ref_post_id) {
      router.push(`/post/${n.ref_post_id}`);
    } else if (n.from_did) {
      router.push(`/agents/${encodeURIComponent(n.from_did)}`);
    } else {
      router.push("/notifications");
    }
  }

  async function onMarkAll() {
    const tok = getToken();
    if (!tok || markingAll) return;
    setMarkingAll(true);
    try {
      await markAllNotifsRead(tok);
      setItems((prev) => prev.map((x) => ({ ...x, is_read: true })));
      setUnread(0);
    } catch { /* swallow */ } finally {
      setMarkingAll(false);
    }
  }

  if (!loggedIn) return null;

  return (
    <div ref={wrapperRef} className="relative">
      <Link
        href="/notifications"
        onClick={onBellClick}
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
        aria-haspopup="dialog"
        aria-expanded={open}
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

      {open && (
        <div
          role="dialog"
          aria-label="Recent notifications"
          className="absolute right-0 top-full mt-2 w-[360px] max-w-[calc(100vw-2rem)]
                     rounded-xl border border-slate-200 dark:border-slate-800
                     bg-white dark:bg-slate-900 shadow-lg z-50 overflow-hidden"
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-slate-800">
            <div className="flex items-center gap-2">
              <Bell className="w-4 h-4 text-slate-500" />
              <span className="text-sm font-semibold">Notifications</span>
              {unread > 0 && (
                <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-cyan-500 text-white text-[10px] font-semibold">
                  {unread}
                </span>
              )}
            </div>
            {unread > 0 && (
              <button
                type="button"
                onClick={onMarkAll}
                disabled={markingAll}
                title="Mark all as read"
                aria-label="Mark all as read"
                className="text-xs text-slate-500 hover:text-slate-200 disabled:opacity-50 inline-flex items-center gap-1"
              >
                {markingAll
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  : <CheckCheck className="w-3.5 h-3.5" />}
                Mark all
              </button>
            )}
          </div>

          {loading && (
            <div className="px-4 py-8 text-center text-sm text-slate-500">
              <Loader2 className="w-4 h-4 animate-spin mx-auto mb-2" />
              Loading…
            </div>
          )}

          {!loading && previewLoaded && items.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-slate-500">
              No notifications yet.
            </div>
          )}

          {!loading && items.length > 0 && (
            <ul className="max-h-[360px] overflow-y-auto">
              {items.map((n) => {
                const icon = NOTIF_ICONS[n.notif_type] ?? "notifications";
                return (
                  <li key={n.notif_id}>
                    <button
                      type="button"
                      onClick={() => onRowClick(n)}
                      className={`w-full text-left flex items-start gap-3 px-4 py-3 border-b border-slate-100 dark:border-slate-800 last:border-0 transition-colors ${
                        n.is_read
                          ? "hover:bg-slate-50 dark:hover:bg-slate-800/40"
                          : "bg-cyan-50/40 dark:bg-cyan-950/20 hover:bg-cyan-50 dark:hover:bg-cyan-950/40"
                      }`}
                    >
                      <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                        <span className="material-symbols-outlined text-primary text-sm">
                          {icon}
                        </span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-slate-800 dark:text-slate-100 truncate">
                          {describe(n)}
                        </p>
                        <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">
                          {timeAgo(n.created_at)}
                        </p>
                      </div>
                      {!n.is_read && (
                        <span
                          aria-label="Unread"
                          className="w-2 h-2 rounded-full bg-cyan-500 mt-1.5 flex-shrink-0"
                        />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          <Link
            href="/notifications"
            onClick={() => setOpen(false)}
            className="block text-center text-xs font-medium text-cyan-500 hover:text-cyan-400 px-4 py-2.5 border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
          >
            See all notifications →
          </Link>
        </div>
      )}
    </div>
  );
}
