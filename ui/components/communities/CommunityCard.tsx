import Link from "next/link";

export function CommunityCard({
  community,
}: {
  community: Record<string, unknown>;
}) {
  return (
    <Link
      href={`/communities/${community.community_id as string}`}
      title={`View ${community.name as string} community`}
      className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors
                 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60
                 focus-visible:ring-offset-2 focus-visible:ring-offset-background-light
                 dark:focus-visible:ring-offset-background-dark"
    >
      <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
        <span className="material-symbols-outlined text-primary text-base">
          group
        </span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">
          {community.name as string}
        </p>
        <p className="text-xs text-slate-500">
          {community.member_count as number} members
        </p>
      </div>
    </Link>
  );
}
