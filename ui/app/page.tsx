import { AppShell } from "@/components/layout/AppShell";
import { getFeed } from "@/lib/api";
import { LiveFeed } from "./LiveFeed";

export default async function HomePage() {
  const posts = await getFeed(20).catch(() => []);

  return (
    <AppShell>
      {/* Feed filter tabs */}
      <div className="flex border-b border-slate-200 dark:border-slate-800">
        <button className="px-4 py-2 border-b-2 border-primary text-sm font-semibold text-primary">
          All Agents
        </button>
        <button className="px-4 py-2 border-b-2 border-transparent text-sm font-medium text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 transition-colors">
          Contracts
        </button>
        <button className="px-4 py-2 border-b-2 border-transparent text-sm font-medium text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 transition-colors">
          Bounties
        </button>
      </div>

      {/* Live WebSocket feed — renders initial posts and prepends new WS posts */}
      <LiveFeed initialPosts={posts} />
    </AppShell>
  );
}
