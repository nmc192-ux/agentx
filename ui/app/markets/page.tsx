import { redirect } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { BountyCard } from "@/components/marketplace/BountyCard";
import { ContractCard } from "@/components/marketplace/ContractCard";
import { getMarkets, getContracts } from "@/lib/api";
import { FEATURE_ECONOMY } from "@/lib/flags";

export default async function MarketsPage() {
  if (!FEATURE_ECONOMY) redirect("/");
  const [bounties, contracts] = await Promise.all([
    getMarkets().catch(() => []),
    getContracts().catch(() => []),
  ]);

  return (
    <AppShell wide>
      <div>
        <h1 className="text-2xl font-bold mb-1">Marketplace</h1>
        <p className="text-slate-500 text-sm mb-6">
          Open bounties, active contracts, and task opportunities
        </p>
      </div>

      {/* Tab filters */}
      <div className="flex border-b border-slate-200 dark:border-slate-800">
        <button className="px-4 py-2 border-b-2 border-primary text-sm font-semibold text-primary">
          Open Bounties
        </button>
        <button className="px-4 py-2 border-b-2 border-transparent text-sm font-medium text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 transition-colors">
          Active Contracts
        </button>
        <button className="px-4 py-2 border-b-2 border-transparent text-sm font-medium text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 transition-colors">
          Your Tasks
        </button>
      </div>

      {/* Bounties */}
      <section>
        <h2 className="text-base font-semibold mb-3">
          Open Bounties ({(bounties as Record<string, unknown>[]).length})
        </h2>
        {(bounties as Record<string, unknown>[]).length === 0 ? (
          <div className="text-center py-10 text-slate-400">
            <span className="material-symbols-outlined text-3xl block mb-2">
              storefront
            </span>
            <p className="text-sm">No open bounties</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(bounties as Record<string, unknown>[]).map((b, i) => (
              <BountyCard key={(b.bounty_id as string) ?? i} bounty={b} />
            ))}
          </div>
        )}
      </section>

      {/* Contracts */}
      {(contracts as Record<string, unknown>[]).length > 0 && (
        <section>
          <h2 className="text-base font-semibold mb-3">
            Recent Contracts ({(contracts as Record<string, unknown>[]).length})
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(contracts as Record<string, unknown>[]).map((c, i) => (
              <ContractCard key={(c.contract_id as string) ?? i} contract={c} />
            ))}
          </div>
        </section>
      )}
    </AppShell>
  );
}
