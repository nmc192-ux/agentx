import { AppShell } from "@/components/layout/AppShell";
import { CivilizationMap } from "@/components/map/CivilizationMap";
import { getTrustNetwork } from "@/lib/api";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function TrustNetworkPage({
  params,
}: {
  params: Promise<{ did: string }>;
}) {
  const { did } = await params;
  const decodedDid = decodeURIComponent(did);
  const network = await getTrustNetwork(decodedDid).catch(() => null);

  const nodes = Array.isArray(network)
    ? (network as Record<string, unknown>[])
    : (network?.nodes as Record<string, unknown>[]) ?? [];

  return (
    <AppShell wide>
      <div className="flex items-center gap-3">
        <Link
          href={`/agents/${encodeURIComponent(decodedDid)}`}
          className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        >
          <span className="material-symbols-outlined text-slate-500">
            arrow_back
          </span>
        </Link>
        <div>
          <h1 className="text-xl font-bold">Trust Network</h1>
          <p className="text-xs text-slate-500 font-mono truncate">
            {decodedDid}
          </p>
        </div>
      </div>

      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-4">
        <p className="text-sm text-slate-500 mb-4">
          {nodes.length} connected nodes visualised
        </p>
        <CivilizationMap
          nodes={nodes.map((n) => ({
            agent_did: (n.agent_did as string) ?? (n.did as string) ?? "",
            trust_score: (n.trust_score as number) ?? 0,
            display_name: n.display_name as string | undefined,
          }))}
        />
      </div>
    </AppShell>
  );
}
