import { AppShell } from "@/components/layout/AppShell";
import { PostTypeGuide } from "@/components/feed/PostTypeGuide";
import { LivePulseSidebar } from "@/components/pulse/LivePulseSidebar";
import { getFeed } from "@/lib/api";
import { LiveFeed } from "./LiveFeed";
import type { SocialPost } from "@/types";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const posts = (await getFeed(20).catch(() => [])) as SocialPost[];

  return (
    <AppShell wide>
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
        <div className="min-w-0">
          {/* Live WebSocket feed — renders composer + initial posts + live WS posts */}
          <LiveFeed initialPosts={posts} />
        </div>
        <aside className="hidden lg:flex flex-col gap-4 sticky top-6">
          <PostTypeGuide />
          <LivePulseSidebar />
        </aside>
      </div>
    </AppShell>
  );
}
