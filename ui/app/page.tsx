import { AppShell } from "@/components/layout/AppShell";
import { getFeed } from "@/lib/api";
import { LiveFeed } from "./LiveFeed";
import type { SocialPost } from "@/types";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const posts = (await getFeed(20).catch(() => [])) as SocialPost[];

  return (
    <AppShell>
      {/* Live WebSocket feed — renders initial posts and prepends new WS posts */}
      <LiveFeed initialPosts={posts} />
    </AppShell>
  );
}
