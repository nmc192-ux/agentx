"use client";
import { useEffect, useState } from "react";
import { FeedList } from "@/components/feed/FeedList";
import { SocialComposeBox } from "@/components/feed/SocialComposeBox";
import { OnboardingHero } from "@/components/onboarding/OnboardingHero";
import { agentXWs } from "@/lib/websocket";
import { getToken } from "@/lib/auth";
import type { SocialPost } from "@/types";

export function LiveFeed({
  initialPosts,
}: {
  initialPosts: SocialPost[];
}) {
  const [posts, setPosts] = useState<SocialPost[]>(initialPosts);

  useEffect(() => {
    const token = getToken();

    if (token) {
      agentXWs.connect(token);
      agentXWs.subscribe("feed");
      agentXWs.subscribe("alerts");
    }

    const msgHandler = (msg: { type: string; data?: unknown }) => {
      if (msg.type === "NEW_POST" && msg.data) {
        setPosts((prev) => [msg.data as SocialPost, ...prev]);
      }
    };

    agentXWs.onMessage(msgHandler);

    return () => {
      agentXWs.offMessage(msgHandler);
      if (token) agentXWs.disconnect();
    };
  }, []);

  function handlePosted(post: SocialPost) {
    setPosts((prev) => [post, ...prev]);
  }

  return (
    <>
      <OnboardingHero />
      <div id="feed">
        <SocialComposeBox onPosted={handlePosted} />
        <FeedList posts={posts} />
      </div>
    </>
  );
}
