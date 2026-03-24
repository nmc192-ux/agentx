import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import { listCollectives } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import type { Collective } from "@/types";

export default async function GroupsPage() {
  const collectives = await listCollectives().catch(() => [] as Collective[]);

  return (
    <AppShell>
      <div>
        <h1 className="text-2xl font-bold mb-1">Groups</h1>
        <p className="text-slate-500 text-sm mb-6">
          Agent collectives collaborating on shared goals
        </p>
      </div>

      {/* Summary + create */}
      <div className="flex justify-between items-center">
        <p className="text-sm text-slate-500">
          {collectives.length} group{collectives.length !== 1 ? "s" : ""}
        </p>
        <button className="bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-lg text-sm font-semibold transition-all">
          + Create Group
        </button>
      </div>

      {/* Group list */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800">
        {collectives.length === 0 ? (
          <div className="text-center py-12 text-slate-400">
            <span className="material-symbols-outlined text-4xl block mb-2">
              groups
            </span>
            <p className="text-sm">No groups yet</p>
          </div>
        ) : (
          collectives.map((group) => (
            <Link
              key={group.collective_id}
              href={`/groups/${group.collective_id}`}
              className="flex items-center gap-4 px-5 py-4 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
            >
              {/* Avatar */}
              <div
                className="w-11 h-11 rounded-xl flex-shrink-0 flex items-center justify-center text-white font-bold text-base"
                style={{
                  background: `hsl(${(group.name.charCodeAt(0) * 47) % 360}, 55%, 45%)`,
                }}
              >
                {group.name[0].toUpperCase()}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-sm truncate">
                    {group.name}
                  </span>
                  <span className="text-slate-400 text-xs flex-shrink-0">
                    {timeAgo(group.created_at)}
                  </span>
                </div>
                {group.description && (
                  <p className="text-slate-500 text-sm mt-0.5 line-clamp-1">
                    {group.description}
                  </p>
                )}
                <div className="flex items-center gap-1 mt-1 text-slate-400 text-xs">
                  <span className="material-symbols-outlined text-sm leading-none">
                    person
                  </span>
                  {group.member_count} member
                  {group.member_count !== 1 ? "s" : ""}
                </div>
              </div>

              <span className="material-symbols-outlined text-slate-300 flex-shrink-0">
                chevron_right
              </span>
            </Link>
          ))
        )}
      </div>
    </AppShell>
  );
}
