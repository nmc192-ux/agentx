export function ContractCard({
  contract,
}: {
  contract: Record<string, unknown>;
}) {
  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-5 hover:shadow-md transition-all">
      <div className="flex items-start justify-between mb-3">
        <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/10 text-green-500 font-semibold capitalize">
          {(contract.status as string) ?? "active"}
        </span>
      </div>
      <h3 className="font-semibold text-sm mb-2">
        {(contract.title as string) ?? "Untitled Contract"}
      </h3>
      <p className="text-xs text-slate-500 line-clamp-2">
        {(contract.terms as string) ?? (contract.description as string)}
      </p>
    </div>
  );
}
