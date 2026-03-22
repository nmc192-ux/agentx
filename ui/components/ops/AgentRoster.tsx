"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type AgentStatus = "ACTIVE" | "IDLE" | "OFFLINE";

interface RosterAgent {
  agent_id: string;
  agent_did: string;
  display_name: string;
  trust_score: number;
  last_seen_at: string | null;
  status: AgentStatus;
}

function deriveStatus(lastSeenAt: string | null): AgentStatus {
  if (!lastSeenAt) return "OFFLINE";
  const diffMs = Date.now() - new Date(lastSeenAt).getTime();
  if (diffMs < 60_000) return "ACTIVE";
  if (diffMs < 300_000) return "IDLE";
  return "OFFLINE";
}

const STATUS_DOT: Record<AgentStatus, string> = {
  ACTIVE:  "bg-green-500",
  IDLE:    "bg-yellow-400",
  OFFLINE: "bg-slate-400",
};

const STATUS_LABEL: Record<AgentStatus, string> = {
  ACTIVE:  "Active",
  IDLE:    "Idle",
  OFFLINE: "Offline",
};

export function AgentRoster() {
  const [agents, setAgents] = useState<RosterAgent[]>([]);

  useEffect(() => {
    async function fetchAgents() {
      try {
        const r = await fetch(`${BASE}/agents?limit=30`, { cache: "no-store" });
        if (!r.ok) return;
        const data = await r.json();
        const raw: Record<string, unknown>[] = Array.isArray(data)
          ? data
          : Array.isArray(data?.agents)
          ? data.agents
          : [];
        setAgents(
          raw.map((a) => ({
            agent_id:     a.agent_id as string,
            agent_did:    a.agent_did as string,
            display_name: (a.display_name as string) ?? (a.agent_did as string),
            trust_score:  (a.trust_score as number) ?? 0,
            last_seen_at: (a.last_seen_at as string) ?? null,
            status:       deriveStatus((a.last_seen_at as string) ?? null),
          }))
        );
      } catch { /* non-fatal */ }
    }
    fetchAgents();
    const t = setInterval(fetchAgents, 10_000);
    return () => clearInterval(t);
  }, []);

  return (
    <aside className="w-60 flex-shrink-0 flex flex-col border-r border-slate-200 dark:border-slate-800 overflow-y-auto">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Agents ({agents.length})
        </p>
      </div>
      <div className="flex-1">
        {agents.length === 0 ? (
          <p className="text-xs text-slate-400 text-center py-8">Loading agents…</p>
        ) : (
          agents.map((a) => (
            <Link
              key={a.agent_did}
              href={`/agents/${a.agent_did}`}
              className="flex items-center gap-2.5 px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors group"
            >
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[a.status]}`} />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium truncate group-hover:text-primary transition-colors">
                  {a.display_name}
                </p>
                <p className="text-xs text-slate-400">{STATUS_LABEL[a.status]}</p>
              </div>
            </Link>
          ))
        )}
      </div>
    </aside>
  );
}
