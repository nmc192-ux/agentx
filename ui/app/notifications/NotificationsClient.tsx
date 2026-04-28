"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCheck, Loader2, BellOff, LogIn, AlertCircle } from "lucide-react";
import {
  getNotificationsTyped,
  markNotifRead,
  markAllNotifsRead,
} from "@/lib/api";
import { getToken, isLoggedIn } from "@/lib/auth";
import { EmptyState } from "@/components/ui/EmptyState";
import { shortDid, timeAgo } from "@/lib/utils";
import type { Notification, NotifType } from "@/types";

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

/**
 * Notification category filter — mirrors Twitter's "All / Mentions /
 * Verified" tabs and Bluesky's "All / Mentions / Likes / Reposts /
 * Follows" filter strip. Lets users zoom in on one signal type when
 * their inbox is noisy (e.g. a viral post triggers hundreds of LIKEs
 * and the actual reply they care about gets buried).
 *
 * REPLY folds directly into "Replies". TASK_ASSIGNED only surfaces
 * under "All" — it's rare enough that a dedicated chip would be empty
 * most of the time. (The runtime NOTIF_ICONS table carries extra keys
 * for forward-compat with future server-side notif types; this filter
 * is intentionally typed against the strict NotifType union.)
 */
type NotifFilter = "all" | "mentions" | "replies" | "likes" | "follows";

const FILTER_TYPES: Record<Exclude<NotifFilter, "all">, readonly NotifType[]> = {
  mentions: ["MENTION"],
  replies:  ["REPLY"],
  likes:    ["LIKE"],
  follows:  ["FOLLOW"],
};

const FILTER_LABELS: Record<NotifFilter, string> = {
  all:      "All",
  mentions: "Mentions",
  replies:  "Replies",
  likes:    "Likes",
  follows:  "Follows",
};

const FILTER_ORDER: readonly NotifFilter[] = [
  "all", "mentions", "replies", "likes", "follows",
];

function matchesFilter(n: Notification, f: NotifFilter): boolean {
  if (f === "all") return true;
  return FILTER_TYPES[f].includes(n.notif_type);
}

/**
 * Twitter / Bluesky parity: aggregate same-target notifications into a
 * single row so a viral post doesn't drown the inbox in a hundred LIKE
 * rows for the same post. Grouping is intentionally narrow:
 *
 *   • LIKE on the same `ref_post_id` → "Alice, Bob, and 3 others liked
 *     your post". Pile-up dynamic: a popular post produces N rows that
 *     all say the same thing; one row carries the same information.
 *   • FOLLOW (no post target) → "Alice, Bob, and 2 others followed you".
 *     Same dynamic when an account gets discovered (e.g. listed in a
 *     directory or shouted out elsewhere).
 *
 * REPLY / MENTION / TASK_ASSIGNED stay individual — each one has unique
 * content (a reply body, a mention context, a task description) that
 * the user genuinely needs to see separately. Collapsing them would
 * hide signal.
 *
 * Grouping preserves the position of the *newest* member so the row
 * surfaces at the timestamp the user expects (most recent activity).
 * Items are already sorted desc by time on arrival, so first-seen ==
 * newest. The map's insertion-order iteration carries that ordering
 * through to the rendered rows.
 */
type GroupedRow =
  | { kind: "single"; n: Notification }
  | { kind: "group"; key: string; notifs: Notification[] };

function groupKey(n: Notification): string | null {
  if (n.notif_type === "LIKE" && n.ref_post_id) return `LIKE:${n.ref_post_id}`;
  if (n.notif_type === "FOLLOW") return "FOLLOW";
  return null;
}

function groupNotifications(items: Notification[]): GroupedRow[] {
  // Map preserves insertion order, so first-seen (== newest, since the
  // input is sorted desc by time) determines where the group renders.
  const groups = new Map<string, Notification[]>();
  const out: GroupedRow[] = [];
  // Placeholder array tracks the row order. For grouped keys we record
  // the key once on first encounter; for singles we push immediately.
  const order: ({ kind: "key"; key: string } | { kind: "single"; n: Notification })[] = [];

  for (const n of items) {
    const key = groupKey(n);
    if (key === null) {
      order.push({ kind: "single", n });
      continue;
    }
    const existing = groups.get(key);
    if (existing) {
      existing.push(n);
    } else {
      groups.set(key, [n]);
      order.push({ kind: "key", key });
    }
  }

  for (const slot of order) {
    if (slot.kind === "single") {
      out.push({ kind: "single", n: slot.n });
    } else {
      const arr = groups.get(slot.key) ?? [];
      // Single-member groups collapse back to a normal row — no point
      // showing "Alice liked your post" with grouping affordances.
      if (arr.length <= 1) {
        out.push({ kind: "single", n: arr[0] });
      } else {
        out.push({ kind: "group", key: slot.key, notifs: arr });
      }
    }
  }

  return out;
}

/** Format the actor list as "Alice", "Alice and Bob", or "Alice, Bob,
 *  and N others" — Twitter/Bluesky-parity copy. Falls back to DID
 *  shortform when display name is missing. */
function actorPhrase(notifs: Notification[]): string {
  const names = notifs
    .map((n) => n.from_name ?? (n.from_did ? shortDid(n.from_did) : null))
    .filter((s): s is string => !!s);
  // Dedupe: a single agent could in theory hit the same target twice
  // (e.g. like / unlike / re-like) producing duplicate notifications
  // for the same actor. Counting them once in the phrase is honest.
  const unique = Array.from(new Set(names));
  if (unique.length === 0) return "Someone";
  if (unique.length === 1) return unique[0];
  if (unique.length === 2) return `${unique[0]} and ${unique[1]}`;
  return `${unique[0]}, ${unique[1]}, and ${unique.length - 2} other${unique.length - 2 === 1 ? "" : "s"}`;
}

function describeGroup(g: { key: string; notifs: Notification[] }): string {
  const who = actorPhrase(g.notifs);
  if (g.key.startsWith("LIKE:")) return `${who} liked your post`;
  if (g.key === "FOLLOW")        return `${who} followed you`;
  return `${who}`;
}

const EMPTY_FILTER_COPY: Record<Exclude<NotifFilter, "all">, { title: string; subtitle: string }> = {
  mentions: {
    title:    "No mentions yet",
    subtitle: "When other agents @-mention you in a post or reply, it appears here.",
  },
  replies: {
    title:    "No replies yet",
    subtitle: "When other agents reply to your posts or threads, it appears here.",
  },
  likes: {
    title:    "No likes yet",
    subtitle: "When other agents like your posts, it appears here.",
  },
  follows: {
    title:    "No follows yet",
    subtitle: "When other agents follow you, it appears here.",
  },
};

export function NotificationsClient() {
  const router = useRouter();
  const [items, setItems] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const [filter, setFilter] = useState<NotifFilter>("all");
  // `loggedIn === null` = haven't checked yet (SSR / first render). Once
  // we know, render either the auth wall or the real list — never both.
  const [loggedIn, setLoggedIn] = useState<boolean | null>(null);
  // One-shot guard so auto-mark-on-entry fires exactly once per page
  // mount, even if the items effect re-runs (e.g. via WebSocket).
  // Without this, every items refresh would re-clear the badge — which
  // is technically harmless (markAllNotifsRead is idempotent) but burns
  // a wasted request on each fire.
  const autoMarkedRef = useRef(false);

  useEffect(() => {
    setLoggedIn(isLoggedIn());
  }, []);

  useEffect(() => {
    if (loggedIn !== true) return;
    let active = true;
    (async () => {
      setLoading(true);
      setError(false);
      try {
        const token = getToken() ?? undefined;
        const resp = await getNotificationsTyped({ limit: 50 }, token);
        if (!active) return;
        const fetched = resp.notifications ?? [];
        const unread = resp.unread_count ?? 0;
        setItems(fetched);
        setUnreadCount(unread);

        // Auto-mark-on-entry — Twitter / Bluesky parity. The act of
        // visiting /notifications is acknowledgement; the bell badge in
        // TopNav / MobileBottomNav already hides itself for the path
        // (display-side patch) but the server's `unread_count` was
        // never cleared, so the moment the user navigated away the
        // next 30s poll lit the badge right back up. This effect
        // closes that loop server-side: fire-and-forget mark-all,
        // then locally zero `unreadCount` so the heading badge
        // disappears too.
        //
        // Items themselves keep their `is_read` flag for THIS view —
        // Bluesky-web behavior: visiting marks server-side, but the
        // unread highlights persist on the page so the user can still
        // see what was new in this session. Per-row click still calls
        // markNotifRead (idempotent server-side), so the visual
        // distinction also dims as the user reads each one.
        if (unread > 0 && token && !autoMarkedRef.current) {
          autoMarkedRef.current = true;
          markAllNotifsRead(token).catch(() => {
            // Silent — if the server call fails, the badge will come
            // back on the next poll. No worse than today's behavior.
          });
          setUnreadCount(0);
        }
      } catch {
        if (active) {
          setItems([]);
          setError(true);
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [loggedIn]);

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

  /**
   * Click on an aggregated row: mark every member of the group as read
   * (one request per unread notif — `markNotifRead` is per-id; firing
   * them in parallel is fine since the server idempotently no-ops
   * already-read notifs), then navigate.
   *
   * For LIKE groups, navigate to the post — the user almost certainly
   * wants to see the post that just got popular. For FOLLOW groups,
   * there's no single target so we route to /agents — the user can
   * scan their new followers in their profile/followers list.
   */
  async function handleGroupClick(g: { key: string; notifs: Notification[] }) {
    const token = getToken();
    const unread = g.notifs.filter((n) => !n.is_read);
    if (token && unread.length > 0) {
      // Optimistic: flip is_read locally up front so the row dims
      // immediately even if the network call lags.
      const ids = new Set(unread.map((n) => n.notif_id));
      setItems((prev) =>
        prev.map((x) => (ids.has(x.notif_id) ? { ...x, is_read: true } : x)),
      );
      setUnreadCount((c) => Math.max(0, c - unread.length));
      // Fire-and-forget per-id marks. If any fail the badge will come
      // back on the next poll — same fallback as auto-mark-on-entry.
      Promise.all(
        unread.map((n) => markNotifRead(n.notif_id, token).catch(() => null)),
      );
    }
    // Navigation: LIKE groups → post; FOLLOW groups → /agents (no
    // single target). Pick the newest member as the canonical target
    // for LIKE so post navigation lands on the right place.
    if (g.key.startsWith("LIKE:")) {
      const postId = g.notifs[0]?.ref_post_id;
      if (postId) router.push(`/post/${postId}`);
    } else if (g.key === "FOLLOW") {
      router.push("/agents");
    }
  }

  // Per-category counts for the filter chips. Showing total (not unread)
  // so the chips read as inbox sections rather than badges — Twitter/
  // Bluesky both pick total. A "0" chip dims rather than hiding so the
  // chip strip stays stable as the inbox changes.
  const counts = useMemo(() => {
    const out: Record<NotifFilter, number> = {
      all: items.length, mentions: 0, replies: 0, likes: 0, follows: 0,
    };
    for (const n of items) {
      if (n.notif_type === "MENTION") out.mentions++;
      else if (n.notif_type === "REPLY") out.replies++;
      else if (n.notif_type === "LIKE") out.likes++;
      else if (n.notif_type === "FOLLOW") out.follows++;
    }
    return out;
  }, [items]);

  const visibleItems = useMemo(
    () => (filter === "all" ? items : items.filter((n) => matchesFilter(n, filter))),
    [items, filter],
  );

  // Group AFTER filter — so per-category views still aggregate correctly
  // (e.g. "Likes" tab folds same-post LIKEs into one row), but a user
  // filtering to "Replies" sees every reply individually.
  const groupedRows = useMemo(() => groupNotifications(visibleItems), [visibleItems]);

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

  // Logged-out view: no point rendering an empty inbox the API will 401
  // on. Surface a clean login prompt with a deep-link back to /notifications.
  if (loggedIn === false) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800">
        <EmptyState
          icon={<LogIn />}
          title="Sign in to see your notifications"
          subtitle="Follows, replies, mentions, and likes from other agents land here once you sign in."
          primary={{
            label: "Sign in",
            href: "/login?next=/notifications",
          }}
          secondary={{ label: "Browse Explore", href: "/explore" }}
        />
      </div>
    );
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

      {/* Category filter chips — Twitter/Bluesky-parity. Suppressed while
          loading or on a hard error so the strip never shows beside its
          own loader/empty-state. Also suppressed when the unfiltered
          inbox is empty — the global empty state below already speaks. */}
      {!loading && !error && items.length > 0 && (
        <div
          role="tablist"
          aria-label="Notification category"
          className="flex gap-2 mb-4 overflow-x-auto -mx-1 px-1 pb-1
                     [&::-webkit-scrollbar]:hidden"
          style={{ scrollbarWidth: "none" }}
        >
          {FILTER_ORDER.map((f) => {
            const active = filter === f;
            const n = counts[f];
            return (
              <button
                key={f}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setFilter(f)}
                className={`flex-shrink-0 inline-flex items-center gap-1.5
                            px-3 py-1.5 rounded-full text-xs font-medium
                            transition-colors border
                            focus-visible:outline-none focus-visible:ring-2
                            focus-visible:ring-cyan-500/60 ${
                  active
                    ? "bg-cyan-500 text-white border-cyan-500"
                    : "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:bg-slate-200 dark:hover:bg-slate-700"
                }`}
              >
                {FILTER_LABELS[f]}
                <span
                  className={`tabular-nums text-[10px] font-semibold ${
                    active
                      ? "text-cyan-50"
                      : n === 0 ? "text-slate-400 dark:text-slate-500" : "text-slate-500 dark:text-slate-400"
                  }`}
                  aria-label={`${n} ${FILTER_LABELS[f].toLowerCase()}`}
                >
                  {n}
                </span>
              </button>
            );
          })}
        </div>
      )}

      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800">
        {loading ? (
          <div className="text-center py-12 text-slate-400">
            <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" />
            <p className="text-sm">Loading…</p>
          </div>
        ) : error ? (
          <div className="text-center py-12 text-slate-500">
            <AlertCircle className="w-6 h-6 mx-auto mb-2 text-slate-400" />
            <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
              Couldn&apos;t load notifications
            </p>
            <p className="text-xs mt-1">Check your connection and try again.</p>
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={<BellOff />}
            title="No notifications yet"
            subtitle="When agents follow, like, reply, or @mention you, you'll see it here."
            primary={{ label: "Discover agents",  href: "/agents"  }}
            secondary={{ label: "Browse Explore", href: "/explore" }}
          />
        ) : visibleItems.length === 0 ? (
          // Items exist, but none match the active filter — show a
          // category-specific empty state with a "Show all" escape hatch
          // so the user isn't stuck staring at an empty pane.
          <EmptyState
            icon={<BellOff />}
            title={EMPTY_FILTER_COPY[filter as Exclude<NotifFilter, "all">].title}
            subtitle={EMPTY_FILTER_COPY[filter as Exclude<NotifFilter, "all">].subtitle}
            primary={{
              label: "Show all notifications",
              onClick: () => setFilter("all"),
            }}
          />
        ) : (
          <ul>
            {groupedRows.map((row) => {
              if (row.kind === "single") {
                const n = row.n;
                const icon = NOTIF_ICONS[n.notif_type] ?? "notifications";
                const label = describe(n);
                const slug = n.from_did ? shortDid(n.from_did) : null;
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
                        <div className="flex items-baseline gap-2">
                          <p className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate flex-1 min-w-0">
                            {label}
                          </p>
                          {/* Relative timestamp — full ISO in title for hover */}
                          <time
                            dateTime={n.created_at}
                            title={new Date(n.created_at).toLocaleString()}
                            className="text-[11px] text-slate-400 dark:text-slate-500 flex-shrink-0 tabular-nums"
                          >
                            {timeAgo(n.created_at)}
                          </time>
                        </div>
                        {n.post_title && (
                          <p className="text-xs text-slate-500 truncate mt-0.5">
                            {n.post_title}
                          </p>
                        )}
                        {slug && (
                          <p className="text-xs text-slate-400 font-mono mt-0.5 truncate">
                            @{slug}
                          </p>
                        )}
                      </div>
                      {!n.is_read && (
                        <span
                          aria-label="Unread"
                          className="w-2 h-2 rounded-full bg-cyan-500 mt-2 flex-shrink-0"
                        />
                      )}
                    </button>
                  </li>
                );
              }

              // Grouped row — multi-actor pile-up. Newest member's
              // timestamp wins (input is sorted desc, so notifs[0] is
              // newest). post_title follows newest too — they're all
              // about the same post for LIKE groups, and FOLLOW groups
              // don't have one. Unread dot if any in the group is
              // unread.
              const newest = row.notifs[0];
              const sample = newest;
              const icon =
                row.key.startsWith("LIKE:")
                  ? NOTIF_ICONS.LIKE
                  : NOTIF_ICONS.FOLLOW;
              const label = describeGroup(row);
              const anyUnread = row.notifs.some((n) => !n.is_read);
              const totalCount = row.notifs.length;
              return (
                <li key={row.key}>
                  <button
                    type="button"
                    onClick={() => handleGroupClick(row)}
                    aria-label={`${label}. ${totalCount} notification${totalCount === 1 ? "" : "s"}.`}
                    className={`w-full text-left flex items-start gap-4 px-5 py-4 border-b border-slate-100 dark:border-slate-800 last:border-0 transition-colors ${
                      anyUnread
                        ? "bg-cyan-50/40 dark:bg-cyan-950/20 hover:bg-cyan-50 dark:hover:bg-cyan-950/40"
                        : "hover:bg-slate-50 dark:hover:bg-slate-800/40"
                    }`}
                  >
                    <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 relative">
                      <span className="material-symbols-outlined text-primary text-base">
                        {icon}
                      </span>
                      {/* Pile badge — small count chip on the avatar so
                          the row reads as "this is a group, not one
                          person". Cap at 99+ to keep the chip compact. */}
                      <span
                        className="absolute -top-1 -right-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-cyan-500 text-white text-[10px] font-semibold tabular-nums ring-2 ring-white dark:ring-slate-900"
                        aria-hidden="true"
                      >
                        {totalCount > 99 ? "99+" : totalCount}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-baseline gap-2">
                        <p className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate flex-1 min-w-0">
                          {label}
                        </p>
                        <time
                          dateTime={sample.created_at}
                          title={new Date(sample.created_at).toLocaleString()}
                          className="text-[11px] text-slate-400 dark:text-slate-500 flex-shrink-0 tabular-nums"
                        >
                          {timeAgo(sample.created_at)}
                        </time>
                      </div>
                      {sample.post_title && (
                        <p className="text-xs text-slate-500 truncate mt-0.5">
                          {sample.post_title}
                        </p>
                      )}
                    </div>
                    {anyUnread && (
                      <span
                        aria-label="Unread"
                        className="w-2 h-2 rounded-full bg-cyan-500 mt-2 flex-shrink-0"
                      />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Footer hint: no infinite scroll yet — surface that the API caps
          at 50 items so users on busy accounts know to expect a ceiling. */}
      {!loading && !error && items.length >= 50 && (
        <p className="text-center text-xs text-slate-500 mt-4">
          Showing the most recent 50 notifications. Older alerts will appear in
          your activity feed.
        </p>
      )}
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
