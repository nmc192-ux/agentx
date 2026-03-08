"use client";

/**
 * AgentX — Authenticated Shell Layout
 * Wraps all protected pages with Nav + WebSocket feed subscription.
 * Redirects to /login if no session.
 */
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Nav } from "@/components/Nav";
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

  const { status: wsStatus } = useWebSocket({
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

  return (
    <div className="min-h-screen bg-background-primary">
      <Nav wsStatus={wsStatus} />
      <main className="container mx-auto px-4 py-6 max-w-7xl">
        {children}
      </main>
    </div>
  );
}
