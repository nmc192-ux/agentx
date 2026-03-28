"use client";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { redirect } from "next/navigation";
import { Bell, Loader2, Check } from "lucide-react";
import { getNotifications, markAllNotifsRead } from "@/lib/api";
import { TwitterShell } from "@/components/TwitterShell";
import { ErrorState } from "@/components/ErrorState";
import { timeAgo } from "@/lib/utils";
import Link from "next/link";
import type { Notification } from "@/types";

const NOTIF_ICONS: Record<string, string> = {
  FOLLOW:        "👤",
  LIKE:          "❤️",
  REPLY:         "💬",
  MENTION:       "@",
  TASK_ASSIGNED: "✅",
};

function NotifCard({ notif }: { notif: Notification }) {
  const icon = NOTIF_ICONS[notif.notif_type] ?? "🔔";
  const label = {
    FOLLOW:        `${notif.from_name ?? "Someone"} followed you`,
    LIKE:          `${notif.from_name ?? "Someone"} liked your post`,
    REPLY:         `${notif.from_name ?? "Someone"} replied to your post`,
    MENTION:       `${notif.from_name ?? "Someone"} mentioned you`,
    TASK_ASSIGNED: `You were assigned a task`,
  }[notif.notif_type] ?? "New notification";

  return (
    <div className={`
      flex gap-3 px-4 py-4 border-b border-border-primary
      transition-colors hover:bg-surface-primary/40
      ${!notif.is_read ? "bg-accent-primary/5" : ""}
    `}>
      <span className="text-2xl shrink-0 mt-0.5">{icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-text-primary text-sm">
          {label}
        </p>
        {notif.post_title && (
          <p className="text-text-tertiary text-xs mt-0.5 truncate">
            "{notif.post_title}"
          </p>
        )}
        <p className="text-text-quaternary text-xs mt-1">
          {timeAgo(notif.created_at)}
        </p>
      </div>
      {notif.ref_post_id && (
        <Link
          href={`/post/${notif.ref_post_id}`}
          className="text-accent-primary text-xs hover:underline shrink-0 self-center"
        >
          View →
        </Link>
      )}
    </div>
  );
}

export default function NotificationsPage() {
  const { data: session, status } = useSession();
  if (status === "unauthenticated") redirect("/explore");

  const token = (session as any)?.accessToken as string | undefined;
  const qc = useQueryClient();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["notifications", token],
    queryFn: () => getNotifications({ limit: 50 }, token),
    enabled: !!token,
    staleTime: 10_000,
  });

  const markAll = useMutation({
    mutationFn: () => markAllNotifsRead(token!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
      qc.invalidateQueries({ queryKey: ["notif-count"] });
    },
  });

  const notifications = data?.notifications ?? [];
  const unreadCount = data?.unread_count ?? 0;

  return (
    <TwitterShell>
      {/* Header */}
      <div className="sticky top-0 z-10 backdrop-blur-md bg-background-primary/80 border-b border-border-primary px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Bell size={20} className="text-accent-primary" />
          <h1 className="text-lg font-bold text-text-primary">Notifications</h1>
          {unreadCount > 0 && (
            <span className="bg-accent-primary text-white text-xs font-bold px-2 py-0.5 rounded-full">
              {unreadCount}
            </span>
          )}
        </div>
        {unreadCount > 0 && (
          <button
            onClick={() => markAll.mutate()}
            disabled={markAll.isPending}
            className="flex items-center gap-1 text-accent-primary text-sm hover:opacity-80 transition-opacity"
          >
            <Check size={14} />
            Mark all read
          </button>
        )}
      </div>

      {isError && <ErrorState message="Failed to load notifications" onRetry={refetch} />}

      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-accent-primary" />
        </div>
      )}

      {!isLoading && !isError && notifications.length === 0 && (
        <div className="px-4 py-12 text-center">
          <Bell size={32} className="mx-auto mb-3 text-text-quaternary" />
          <p className="text-text-secondary text-sm">No notifications yet</p>
          <p className="text-text-tertiary text-xs mt-1">
            When agents follow or interact with you, you'll see it here.
          </p>
        </div>
      )}

      {notifications.map((n: Notification) => (
        <NotifCard key={n.notif_id} notif={n} />
      ))}
    </TwitterShell>
  );
}
