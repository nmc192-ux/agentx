import Link from "next/link";
import { ReputationBadge } from "./ReputationBadge";

export function AgentCard({ agent }: { agent: Record<string, unknown> }) {
  const did = (agent.agent_did as string) ?? "";

  return (
    <Link
      href={`/agents/${encodeURIComponent(did)}`}
      title={`View ${(agent.display_name as string) ?? did}'s profile`}
      className="block bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-5 hover:shadow-md hover:border-primary/30 hover:scale-[1.01] transition-all
                 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60
                 focus-visible:ring-offset-2 focus-visible:ring-offset-background-light
                 dark:focus-visible:ring-offset-background-dark"
    >
      <div className="flex items-start justify-between mb-3">
        <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center">
          <span className="material-symbols-outlined text-primary text-2xl">
            smart_toy
          </span>
        </div>
        <ReputationBadge score={(agent.trust_score as number) ?? 0} />
      </div>

      <h3 className="font-semibold text-sm truncate">
        {(agent.display_name as string) ?? did.slice(0, 24)}
      </h3>
      <p className="text-xs text-slate-500 font-mono mt-0.5 truncate">{did}</p>

      {!!(agent.specialization as string) && (
        <p className="text-xs text-slate-400 mt-2 line-clamp-2">
          {agent.specialization as string}
        </p>
      )}

      {/* Economic activity badge */}
      {(agent.eco_influence_score as number) > 0 && (
        <span className="inline-block mt-2 text-xs px-2 py-0.5 bg-yellow-500/10 text-yellow-500 rounded-full">
          ⚡ {(agent.eco_influence_score as number).toFixed(1)} AXT
        </span>
      )}

      {/* Capability tags */}
      {Array.isArray(agent.capabilities) && agent.capabilities.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-3">
          {(agent.capabilities as string[]).slice(0, 3).map((c) => (
            <span
              key={c}
              className="text-xs px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 rounded text-slate-600 dark:text-slate-300"
            >
              {c}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}
