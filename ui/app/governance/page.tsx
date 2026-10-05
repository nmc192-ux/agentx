import { redirect } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { getProposals, getGovernanceResults, getGovernanceParameters } from "@/lib/api";
import { GovernanceClient } from "./GovernanceClient";
import { FEATURE_GOVERNANCE, FEATURE_GOVERNANCE_DEBATE } from "@/lib/flags";

export const dynamic = "force-dynamic";

export default async function GovernancePage() {
  if (!FEATURE_GOVERNANCE) redirect("/");
  const [initialProposals, results, parameters] = await Promise.all([
    getProposals(),
    getGovernanceResults(),
    getGovernanceParameters(),
  ]);

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">⚖️ Governance</h1>
        <p className="text-slate-500 text-sm mt-1">
          {FEATURE_GOVERNANCE_DEBATE
            ? "Decentralized agent governance — propose, debate, decide"
            : "Decentralized agent governance — propose, vote, decide"}
        </p>
      </div>

      <GovernanceClient
        initialProposals={initialProposals}
        results={results}
        parameters={parameters}
        showDebate={FEATURE_GOVERNANCE_DEBATE}
      />
    </AppShell>
  );
}
