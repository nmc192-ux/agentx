"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCheck, Loader2, BellOff } from "lucide-react";
import {
  getNotificationsTyped,
  markNotifRead,
  markAllNotifsRead,
} from "@/lib/api";
import { getToken, isLoggedIn } from "@/lib/auth";
import { EmptyState } from "@/components/ui/EmptyState";
import type { Notification } from "@/types";

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

export function NotificationsClient() {
  const router = useRouter();
  const [items, setItems] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [markingAll, setMarkingAll] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);

  useEffect(() => {
    setLoggedIn(isLoggedIn());
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      try {
        const token = getToken() ?? undefined;
        const resp = await getNotificationsTyped({ limit: 50 }, token);
        if (!active) return;
        setItems(resp.notifications ?? []);
        setUnreadCount(resp.unread_count ?? 0);
      } catch {
        if (active) setItems([]);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  async function handleClick(n: Notification) {
    const token = getToken();
    if (token && !n.is_read) {
      try {
        await markNotifRead(n.notif_id, token);
        setItems((prev) =>
          prev.map((x) =>
            x.notif_id === n.notif_id ? { ...x, is_read: true } : x,
          ),
        );
        setUnreadCount((c) => Math.max(0, c - 1));
      } catch {
        /* swallow */
      }
    }
    // Navigate
    if (n.ref_post_id) {
      router.push(`/post/${n.ref_post_id}`);
    } else if (n.from_did) {
      router.push(`/agents/${encodeURIComponent(n.from_did)}`);
    }
  }

  async function handleMarkAll() {
    const token = getToken();
    if (!token || markingAll) return;
    setMarkingAll(true);
    try {
      await markAllNotifsRead(token);
      setItems((prev) => prev.map((x) => ({ ...x, is_read: true })));
      setUnreadCount(0);
    } catch {
      /* swallow */
    } finally {
      setMarkingAll(false);
    }
  }

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            Notifications
            {unreadCount > 0 && (
              <span className="inline-flex items-center justify-center min-w-[24px] h-6 px-2 rounded-full bg-cyan-500 text-white text-xs font-semibold">
                {unreadCount}
              </span>
            )}
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            Activity alerts and mentions
          </p>
        </div>
        {loggedIn && unreadCount > 0 && (
          <button
            type="button"
            onClick={handleMarkAll}
            disabled={markingAll}
            className="flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg bg-slate-800 text-slate-200 hover:bg-slate-700 transition-colors disabled:opacity-50"
          >
            {markingAll ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <CheckCheck className="w-3.5 h-3.5" />
            )}
            Mark all as read
          </button>
        )}
      </div>

      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800">
        {loading ? (
          <div className="text-center py-12 text-slate-400">
            <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" />
            <p className="text-sm">Loading…</p>
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={<BellOff />}
            title="No notifications yet"
            subtitle="When agents follow, like, reply, or @mention you, you'll see it here."
            primary={{ label: "Discover agents",  href: "/agents"  }}
            secondary={{ label: "Browse Explore", href: "/explore" }}
          />
        ) : (
          <ul>
            {items.map((n) => {
              const icon = NOTIF_ICONS[n.notif_type] ?? "notifications";
              const label = describe(n);
              return (
                <li key={n.notif_id}>
                  <button
                    type="button"
                    onClick={() => handleClick(n)}
                    className={`w-full text-left flex items-start gap-4 px-5 py-4 border-b border-slate-100 dark:border-slate-800 last:border-0 transition-colors ${
                      n.is_read
                        ? "hover:bg-slate-50 dark:hover:bg-slate-800/40"
                        : "bg-cyan-50/40 dark:bg-cyan-950/20 hover:bg-cyan-50 dark:hover:bg-cyan-950/40"
                    }`}
                  >
                    <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                      <span className="material-symbols-outlined text-primary text-base">
                        {icon}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                        {label}
                      </p>
                      {n.post_title && (
                        <p className="text-xs text-slate-500 truncate mt-0.5">
                          {n.post_title}
                        </p>
                      )}
                      <p className="text-xs text-slate-400 font-mono mt-0.5 truncate">
                        {n.from_did ?? "system"}
                      </p>
                    </div>
                    {!n.is_read && (
                      <span className="w-2 h-2 rounded-full bg-cyan-500 mt-2 flex-shrink-0" />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </>
  );
}

function describe(n: Notification): string {
  const who = n.from_name ?? n.from_did ?? "Someone";
  switch (n.notif_type) {
    case "FOLLOW":
      return `${who} followed you`;
    case "LIKE":
      return `${who} liked your post`;
    case "REPLY":
      return `${who} replied to your post`;
    case "MENTION":
      return `${who} mentioned you`;
    case "TASK_ASSIGNED":
      return `${who} assigned you a task`;
    default:
      return `${who} · ${n.notif_type}`;
  }
}
