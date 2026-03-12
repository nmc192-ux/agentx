"use client";

import { useEffect, useState } from "react";

const API_BASE = "http://localhost:8000";
const REFRESH_MS = 3000;

type AgentItem = {
  agent_did: string;
  display_name: string;
  trust_score: number;
  services_count: number;
  tasks_completed: number;
};

async function fetchAgents(): Promise<AgentItem[]> {
  const response = await fetch(`${API_BASE}/dashboard/agents`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch agents");
  }

  return response.json();
}

export function AgentCard() {
  const [agents, setAgents] = useState<AgentItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const load = async () => {
      try {
        const nextAgents = await fetchAgents();
        if (!active) {
          return;
        }
        setAgents(nextAgents);
        setError(null);
      } catch {
        if (!active) {
          return;
        }
        setError("Agent summary unavailable");
      }
    };

    void load();
    const timer = window.setInterval(() => {
      void load();
    }, REFRESH_MS);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">Registry</p>
          <h2 className="panel-title">Agents</h2>
        </div>
        <span className="status-chip">{agents.length} online</span>
      </div>

      {error ? <p className="panel-empty">{error}</p> : null}

      <div className="grid gap-3 overflow-y-auto pr-1">
        {agents.slice(0, 8).map((agent) => (
          <article
            key={agent.agent_did}
            className="rounded-2xl border border-white/10 bg-white/5 p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-50">
                  {agent.display_name}
                </h3>
                <p className="mt-1 text-xs text-slate-400">{agent.agent_did}</p>
              </div>
              <div className="rounded-full bg-emerald-400/15 px-3 py-1 text-xs font-semibold text-emerald-200">
                {(agent.trust_score * 100).toFixed(0)}%
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-xl bg-slate-950/40 p-3">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500">
                  Services
                </p>
                <p className="mt-1 text-lg font-semibold text-slate-100">
                  {agent.services_count}
                </p>
              </div>
              <div className="rounded-xl bg-slate-950/40 p-3">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500">
                  Completed
                </p>
                <p className="mt-1 text-lg font-semibold text-slate-100">
                  {agent.tasks_completed}
                </p>
              </div>
            </div>
          </article>
        ))}

        {!error && agents.length === 0 ? (
          <p className="panel-empty">No agents found</p>
        ) : null}
      </div>
    </section>
  );
}
