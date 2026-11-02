import { AppShell } from "@/components/layout/AppShell";
import { RightColumn } from "@/components/home/RightColumn";
import { getHomeTimeline } from "@/lib/api";
import { LiveFeed } from "./LiveFeed";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  // Latest, as a visitor sees it; a signed-in viewer re-reads it in the
  // browser with its token (blocks apply), and can switch to Following.
  const first = await getHomeTimeline("latest").catch(() => null);

  return (
    <AppShell
      wide
      right={<RightColumn />}
    >
      <LiveFeed
        initialPosts={first?.posts ?? []}
        initialCursor={first?.next_cursor ?? null}
        initialFailed={first === null}
      />
    </AppShell>
  );
}
