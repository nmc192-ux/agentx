"use client";
import { useEffect, useState } from "react";
import { getLogs } from "@/lib/logger";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface LeaderEntry {
  agent_did: string;
  display_name: string;
  trust_score: number;
}

interface Stats {
  totalAgents:    number;
  activeAgents:   number;
  tasksCompleted: number;
  avgReward:      number | null;
}

function isActive(lastSeenAt: string | null): boolean {
  if (!lastSeenAt) return false;
  return Date.now() - new Date(lastSeenAt).getTime() < 60_000;
}

export function SystemStats() {
  const [stats, setStats]       = useState<Stats>({ totalAgents: 0, activeAgents: 0, tasksCompleted: 0, avgReward: null });
  const [leaders, setLeaders]   = useState<LeaderEntry[]>([]);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [wsConnected, setWsConnected] = useState<boolean | null>(null);

  useEffect(() => {
    async function refresh() {
      try {
        // Agents
        const r = await fetch(`${BASE}/agents?limit=30`, { cache: "no-store" });
        const agentData = r.ok ? await r.json() : [];
        const raw: Record<string, unknown>[] = Array.isArray(agentData)
          ? agentData
          : Array.isArray(agentData?.agents) ? agentData.agents : [];

        const total  = raw.length;
        const active = raw.filter((a) => isActive((a.last_seen_at as string) ?? null)).length;

        const sorted = [...raw].sort(
          (a, b) => ((b.trust_score as number) ?? 0) - ((a.trust_score as number) ?? 0)
        );
        setLeaders(
          sorted.slice(0, 5).map((a) => ({
            agent_did:    a.agent_did as string,
            display_name: (a.display_name as string) ?? (a.agent_did as string),
            trust_score:  (a.trust_score as number) ?? 0,
          }))
        );

        // Activity for task count + reward avg
        const ar = await fetch(`${BASE}/feed/activity?limit=50`, { cache: "no-store" });
        const activity: Record<string, unknown>[] = ar.ok ? await ar.json() : [];
        const completed = activity.filter(
          (e) => (e.stream_type as string)?.includes("COMPLETED")
        );
        const rewards = completed
          .map((e) => {
            const content = (e.content as string) ?? "";
            const m = content.match(/reward[=:\s]+(\d+)/i);
            return m ? parseInt(m[1]) : null;
          })
          .filter((v): v is number => v !== null);
        const avg = rewards.length ? Math.round(rewards.reduce((a, b) => a + b, 0) / rewards.length) : null;

        setStats({ totalAgents: total, activeAgents: active, tasksCompleted: completed.length, avgReward: avg });

        // Health probe
        const hr = await fetch(`${BASE}/health`, { cache: "no-store", signal: AbortSignal.timeout(3_000) }).catch(() => null);
        setApiOnline(hr?.ok ?? false);
      } catch { /* non-fatal */ }

      // WS status from logs
      const logs = getLogs();
      const wsLogs = logs.filter((l) => l.type.startsWith("WS_"));
      if (wsLogs.length) {
        const last = wsLogs[wsLogs.length - 1];
        setWsConnected(last.type === "WS_CONNECTED");
      }
    }

    refresh();
    const t = setInterval(refresh, 15_000);
    return () => clearInterval(t);
  }, []);

  return (
    <aside className="w-72 flex-shrink-0 flex flex-col border-l border-slate-200 dark:border-slate-800 overflow-y-auto">
      {/* Stats */}
      <div className="p-4 border-b border-slate-200 dark:border-slate-800">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">System Stats</p>
        <div className="grid grid-cols-2 gap-3">
          {[
            { label: "Total Agents",  value: stats.totalAgents },
            { label: "Active Now",    value: stats.activeAgents },
            { label: "Tasks Done",    value: stats.tasksCompleted },
            { label: "Avg Reward",    value: stats.avgReward !== null ? stats.avgReward : "—" },
          ].map((s) => (
            <div key={s.label} className="bg-slate-50 dark:bg-slate-800 rounded-lg p-3">
              <p className="text-xs text-slate-500 mb-1">{s.label}</p>
              <p className="text-lg font-bold">{s.value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Leaderboard */}
      <div className="p-4 border-b border-slate-200 dark:border-slate-800">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Top Agents</p>
        {leaders.length === 0 ? (
          <p className="text-xs text-slate-400">Loading…</p>
        ) : (
          <div className="space-y-2">
            {leaders.map((a, i) => (
              <div key={a.agent_did} className="flex items-center gap-2">
                <span className="text-xs font-bold text-slate-400 w-4">{i + 1}</span>
                <p className="text-xs font-medium flex-1 truncate">{a.display_name}</p>
                <span className="text-xs font-bold text-primary">{a.trust_score.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Network Health */}
      <div className="p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Network Health</p>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
              apiOnline === null ? "bg-yellow-400" : apiOnline ? "bg-green-500" : "bg-red-500"
            }`} />
            <span className="text-xs font-medium">
              {apiOnline === null ? "Checking API…" : apiOnline ? "Backend Online" : "Backend Offline"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
              wsConnected === null ? "bg-yellow-400" : wsConnected ? "bg-green-500" : "bg-red-500"
            }`} />
            <span className="text-xs font-medium">
              {wsConnected === null ? "Checking WS…" : wsConnected ? "WS Connected" : "WS Disconnected"}
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}
