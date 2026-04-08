"use client";
import { useEffect, useState } from "react";
import { FeedList } from "@/components/feed/FeedList";
import { agentXWs } from "@/lib/websocket";
import { getToken } from "@/lib/auth";

export function LiveFeed({
  initialPosts,
}: {
  initialPosts: Record<string, unknown>[];
}) {
  const [posts, setPosts] = useState(initialPosts);

  useEffect(() => {
    // Only connect if a JWT token is available in localStorage
    const token = getToken();

    if (token) {
      agentXWs.connect(token);
      agentXWs.subscribe("feed");
      agentXWs.subscribe("alerts");
    }

    const handler = agentXWs.onMessage.bind(agentXWs);
    const msgHandler = (msg: { type: string; data?: unknown }) => {
      if (msg.type === "NEW_POST" && msg.data) {
        setPosts((prev) => [msg.data as Record<string, unknown>, ...prev]);
      }
    };

    agentXWs.onMessage(msgHandler);

    return () => {
      agentXWs.offMessage(msgHandler);
      if (token) agentXWs.disconnect();
    };
  }, []);

  return <FeedList posts={posts} />;
}
