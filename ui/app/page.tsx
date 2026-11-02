import { AppShell } from "@/components/layout/AppShell";
import { RightColumn } from "@/components/home/RightColumn";
import { getFeed } from "@/lib/api";
import { LiveFeed } from "./LiveFeed";
import type { SocialPost } from "@/types";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const posts = (await getFeed(20).catch(() => [])) as SocialPost[];

  return (
    <AppShell
      wide
      right={<RightColumn />}
    >
      {/* Live WebSocket feed — renders composer + initial posts + live WS posts */}
      <LiveFeed initialPosts={posts} />
    </AppShell>
  );
}
