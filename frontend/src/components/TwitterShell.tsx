"use client";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { LeftSidebar } from "./LeftSidebar";
import { RightSidebar } from "./RightSidebar";
import { getNotifications } from "@/lib/api";

interface Props {
  children: React.ReactNode;
  showRightSidebar?: boolean;
}

export function TwitterShell({ children, showRightSidebar = true }: Props) {
  const { data: session } = useSession();
  const token = (session as any)?.accessToken as string | undefined;

  // Poll unread count for notification badge
  const { data: notifsData } = useQuery({
    queryKey: ["notif-count", token],
    queryFn: () => getNotifications({ limit: 1, unread_only: true }, token),
    enabled: !!token,
    refetchInterval: 30_000,
  });

  const unreadCount = notifsData?.unread_count ?? 0;

  return (
    <div className="flex min-h-screen max-w-7xl mx-auto">
      <LeftSidebar unreadCount={unreadCount} />

      <main className="flex-1 min-w-0 border-r border-border-primary max-w-[600px]">
        {children}
      </main>

      {showRightSidebar && <RightSidebar />}
    </div>
  );
}
