export function CommunityHeader({
  community,
}: {
  community: Record<string, unknown>;
}) {
  return (
    <div className="pb-6 border-b border-slate-200 dark:border-slate-800">
      <div className="flex items-center gap-4">
        <div className="w-16 h-16 rounded-xl bg-gradient-to-br from-primary to-blue-400 flex items-center justify-center">
          <span className="material-symbols-outlined text-white text-3xl">
            group
          </span>
        </div>
        <div>
          <h1 className="text-2xl font-bold">{community.name as string}</h1>
          <p className="text-slate-500 text-sm mt-1">
            {community.description as string}
          </p>
          <div className="flex items-center gap-3 mt-2">
            <span className="text-xs text-slate-400">
              {community.member_count as number} members
            </span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/10 text-green-500 font-semibold capitalize">
              {community.visibility as string}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
