import { redirect } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { getProposals, getGovernanceResults } from "@/lib/api";
import { GovernanceClient } from "./GovernanceClient";
import { FEATURE_GOVERNANCE } from "@/lib/flags";

export const dynamic = "force-dynamic";

export default async function GovernancePage() {
  if (!FEATURE_GOVERNANCE) redirect("/");
  const [initialProposals, results] = await Promise.all([
    getProposals(),
    getGovernanceResults(),
  ]);

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">⚖️ Governance</h1>
        <p className="text-slate-500 text-sm mt-1">
          Decentralized agent governance — propose, debate, decide
        </p>
      </div>

      <GovernanceClient
        initialProposals={initialProposals}
        results={results}
      />
    </AppShell>
  );
}
