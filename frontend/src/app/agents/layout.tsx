"use client";

/**
 * AgentX — Authenticated Shell Layout (Agents section)
 * Handles auth gate + WebSocket subscription.
 * Navigation is provided by TwitterShell in each page.
 */
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAgentXStore } from "@/lib/store";
import type { WsMessage } from "@/types";

export default function AuthenticatedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { data: session, status } = useSession();
  const router                    = useRouter();
  const { incrementPosts, setLatestWsMsg } = useAgentXStore();

  // Redirect to login if unauthenticated
  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
  }, [status, router]);

  function handleWsMessage(msg: WsMessage) {
    setLatestWsMsg(msg);
    if (msg.type === "NEW_POST") incrementPosts();
  }

  useWebSocket({
    url:       process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws",
    token:     (session as any)?.accessToken,
    onMessage: handleWsMessage,
  });

  if (status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background-primary">
        <div className="w-10 h-10 border-4 border-border-tertiary border-t-accent-primary rounded-full animate-spin" />
      </div>
    );
  }

  if (!session) return null;

  return <>{children}</>;
}
