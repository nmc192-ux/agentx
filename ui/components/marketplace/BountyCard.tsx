export function BountyCard({ bounty }: { bounty: Record<string, unknown> }) {
  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-5 hover:shadow-md hover:border-primary/30 transition-all">
      <div className="flex items-start justify-between mb-3">
        <span className="text-xs px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-500 font-semibold">
          Open Bounty
        </span>
        {bounty.reward_amount != null && (
          <span className="text-sm font-bold text-primary">
            {bounty.reward_amount as number} AXT
          </span>
        )}
      </div>
      <h3 className="font-semibold text-sm mb-2">
        {(bounty.title as string) ?? "Untitled Bounty"}
      </h3>
      <p className="text-xs text-slate-500 line-clamp-2">
        {bounty.description as string}
      </p>
      <button className="mt-4 w-full py-2 rounded-lg border border-primary text-primary text-sm font-semibold hover:bg-primary hover:text-white transition-colors">
        Claim Bounty
      </button>
    </div>
  );
}
