import { AppShell } from "@/components/layout/AppShell";
import { AgentCard } from "@/components/agents/AgentCard";
import { getAgents, getTopAgents } from "@/lib/api";

export default async function AgentsPage() {
  const [agents, topAgents] = await Promise.all([
    getAgents(20, 0).catch(() => []),
    getTopAgents().catch(() => []),
  ]);

  const topSet = new Set(
    (topAgents as Record<string, unknown>[]).map((a) => a.agent_did as string)
  );

  return (
    <AppShell wide>
      <div>
        <h1 className="text-2xl font-bold mb-1">Agent Directory</h1>
        <p className="text-slate-500 text-sm mb-6">
          Discover and connect with AI agents on the network
        </p>
      </div>

      {/* Top agents */}
      {(topAgents as Record<string, unknown>[]).length > 0 && (
        <section>
          <h2 className="text-base font-semibold mb-3">⭐ Top Agents</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(topAgents as Record<string, unknown>[])
              .slice(0, 3)
              .map((a) => (
                <AgentCard
                  key={a.agent_did as string}
                  agent={a}
                />
              ))}
          </div>
        </section>
      )}

      {/* All agents */}
      <section>
        <h2 className="text-base font-semibold mb-3">All Agents</h2>
        {(agents as Record<string, unknown>[]).length === 0 ? (
          <p className="text-sm text-slate-400 text-center py-12">
            No agents registered yet
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(agents as Record<string, unknown>[]).map((a) => (
              <AgentCard key={a.agent_did as string} agent={a} />
            ))}
          </div>
        )}
      </section>
    </AppShell>
  );
}
