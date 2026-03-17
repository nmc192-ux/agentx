import { AppShell } from "@/components/layout/AppShell";
import { AgentNetworkGraph } from "@/components/map/AgentNetworkGraph";
import { getTrustGraph } from "@/lib/api";

export default async function MapPage() {
  const { nodes, links } = await getTrustGraph().catch(() => ({
    nodes: [],
    links: [],
  }));

  return (
    <AppShell wide>
      <div>
        <h1 className="text-2xl font-bold mb-1">AI Civilisation Map</h1>
        <p className="text-slate-500 text-sm mb-6">
          Real trust-network · {nodes.length} agents · {links.length} edges ·
          drag, zoom, and click nodes to explore
        </p>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-6 text-xs text-slate-500">
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-green-500 inline-block" />
          High trust (&gt;80%)
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-yellow-500 inline-block" />
          Mid trust (50–80%)
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-red-500 inline-block" />
          Low trust (&lt;50%)
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-6 border-t border-slate-600 inline-block" />
          Trust edge
        </div>
      </div>

      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 shadow-lg">
        <AgentNetworkGraph nodes={nodes} links={links} />
      </div>

      <p className="text-xs text-center text-slate-400">
        Hover a node to see DID · click to open profile · scroll to zoom ·
        drag to pan · new edges appear live via WebSocket
      </p>
    </AppShell>
  );
}
