"use client";

/**
 * AgentX — Map Page Client Component
 * Wraps ConstellationGraph with agent selector.
 */
import { useState, useEffect } from "react";
import { ConstellationGraph } from "@/components/graph/ConstellationGraph";
import { getTopAgents } from "@/lib/api";

export function MapClient() {
  const [agents, setAgents] = useState<Record<string, unknown>[]>([]);
  const [selected, setSelected] = useState<string>("");

  useEffect(() => {
    (async () => {
      const top = await getTopAgents().catch(() => []);
      setAgents(top);
      if (top.length > 0 && top[0].agent_did) {
        setSelected(String(top[0].agent_did));
      }
    })();
  }, []);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <label className="text-sm text-slate-400">Center agent:</label>
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-cyan-500"
        >
          {agents.map((a) => (
            <option key={String(a.agent_did)} value={String(a.agent_did)}>
              {String(a.display_name ?? a.agent_did)}
            </option>
          ))}
        </select>
      </div>
      {selected && <ConstellationGraph centerDid={selected} />}
    </div>
  );
}
