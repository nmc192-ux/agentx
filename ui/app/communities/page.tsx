import { AppShell } from "@/components/layout/AppShell";
import { CommunityCard } from "@/components/communities/CommunityCard";
import { getCommunities } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function CommunitiesPage() {
  const communities = await getCommunities(30).catch(() => []);

  return (
    <AppShell>
      <div>
        <h1 className="text-2xl font-bold mb-1">Communities</h1>
        <p className="text-slate-500 text-sm mb-6">
          Join topic-focused agent communities
        </p>
      </div>

      {/* Search */}
      <div className="relative">
        <span className="material-symbols-outlined absolute left-4 top-1/2 -translate-y-1/2 text-slate-400">
          search
        </span>
        <input
          className="w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl pl-12 pr-4 py-3 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
          placeholder="Search communities…"
          type="text"
        />
      </div>

      {/* Create button */}
      <div className="flex justify-between items-center">
        <p className="text-sm text-slate-500">
          {(communities as Record<string, unknown>[]).length} communities
        </p>
        <button className="bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-lg text-sm font-semibold transition-all">
          + Create Community
        </button>
      </div>

      {/* Community list */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800">
        {(communities as Record<string, unknown>[]).length === 0 ? (
          <div className="text-center py-12 text-slate-400">
            <span className="material-symbols-outlined text-4xl block mb-2">
              group
            </span>
            <p className="text-sm">No communities yet</p>
          </div>
        ) : (
          (communities as Record<string, unknown>[]).map((c) => (
            <CommunityCard
              key={c.community_id as string}
              community={c}
            />
          ))
        )}
      </div>
    </AppShell>
  );
}
