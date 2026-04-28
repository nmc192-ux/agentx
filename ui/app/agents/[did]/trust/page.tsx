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
  // getTrustNetwork now returns a typed { seed_did, peer_count, nodes }
  // payload — the seed at index 0 plus one node per enriched peer.
  // The previous flat-array fallback is gone because the API helper
  // never produced one (the bug was the helper 422'd silently and the
  // page got null forever).
  const network = await getTrustNetwork(decodedDid).catch(() => null);
  const nodes = network?.nodes ?? [];
  const peerCount = network?.peer_count ?? Math.max(0, nodes.length - 1);

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
          {peerCount === 0 ? (
            <>No trust edges yet — this agent hasn&apos;t been recorded as a peer of anyone in the registry.</>
          ) : (
            <>
              <span className="text-slate-700 dark:text-slate-300 font-medium">
                {peerCount}
              </span>{" "}
              peer{peerCount === 1 ? "" : "s"} visualised, rooted at this agent.
            </>
          )}
        </p>
        <CivilizationMap
          nodes={nodes.map((n) => ({
            agent_did:    n.agent_did,
            trust_score:  n.trust_score,
            display_name: n.display_name ?? undefined,
          }))}
        />
      </div>
    </AppShell>
  );
}
