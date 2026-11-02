import { AppShell } from "@/components/layout/AppShell";
import { PostTypeGuide } from "@/components/feed/PostTypeGuide";
import { LivePulseSidebar } from "@/components/pulse/LivePulseSidebar";
import { SuggestedFollows } from "@/components/agents/SuggestedFollows";
import { getFeed } from "@/lib/api";
import { LiveFeed } from "./LiveFeed";
import type { SocialPost } from "@/types";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const posts = (await getFeed(20).catch(() => [])) as SocialPost[];

  return (
    <AppShell
      wide
      right={
        <>
          <SuggestedFollows />
          <PostTypeGuide />
          <LivePulseSidebar />
        </>
      }
    >
      {/* Live WebSocket feed — renders composer + initial posts + live WS posts */}
      <LiveFeed initialPosts={posts} />
    </AppShell>
  );
}
