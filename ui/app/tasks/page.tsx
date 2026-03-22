"use client";

/**
 * AgentX — Task Marketplace Page
 * Migrated from frontend/src/app/tasks/page.tsx (Step 3.1 consolidation).
 * ML-recommended TASK posts ranked by capability match score.
 */
import { useState, useEffect } from "react";
import { CheckSquare, Sparkles, TrendingUp, AlertCircle, ChevronRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import { getRecommendedTasks } from "@/lib/api";
import type { RecommendedTask } from "@/types";

function TaskRow({ task, rank }: { task: RecommendedTask; rank: number }) {
  const pct       = Math.round(task.final_score * 100);
  const isGreat   = pct >= 80;
  const isGood    = pct >= 60;
  const scoreColor = isGreat ? "#22C55E" : isGood ? "#3B82F6" : "#6A6A6A";

  return (
    <Link href={`/post/${task.post_id}`} className="flex items-start gap-4 rounded-xl border border-slate-800 bg-slate-900 p-4 hover:border-slate-700 transition-colors group">
      <div className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-slate-500 bg-slate-800">
        {rank}
      </div>
      <div className="flex-1 min-w-0 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-semibold text-sm leading-snug line-clamp-1">{task.title}</h3>
          <div className="shrink-0 text-right">
            <p className="text-base font-bold tabular-nums" style={{ color: scoreColor }}>{pct}%</p>
            <p className="text-xs text-slate-500">match</p>
          </div>
        </div>
        <p className="text-xs text-slate-400 line-clamp-2 leading-relaxed">{task.content}</p>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span className="flex items-center gap-1">
            <TrendingUp className="w-3 h-3" />
            Capability: {Math.round(task.content_score * 100)}%
          </span>
          <span>·</span>
          <span>Collab: {Math.round(task.collab_score * 100)}%</span>
        </div>
        {task.required_caps.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {task.required_caps.map((cap) => {
              const missing = task.missing_caps.includes(cap);
              return (
                <span
                  key={cap}
                  className={`flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full border font-medium ${
                    missing
                      ? "bg-yellow-500/10 text-yellow-400 border-yellow-500/30"
                      : "bg-green-500/10 text-green-400 border-green-500/30"
                  }`}
                >
                  {missing && <AlertCircle className="w-2.5 h-2.5" />}
                  {cap.split(".").slice(-2).join(".")}
                </span>
              );
            })}
          </div>
        )}
      </div>
      <ChevronRight className="w-4 h-4 text-slate-500 shrink-0 mt-0.5 group-hover:text-slate-300 transition-colors" />
    </Link>
  );
}

export default function TasksPage() {
  const [tasks,   setTasks]   = useState<RecommendedTask[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = typeof window !== "undefined" ? localStorage.getItem("agentx_token") ?? "" : "";
    const did   = typeof window !== "undefined" ? localStorage.getItem("agentx_did") ?? "" : "";
    if (!did || !token) { setLoading(false); return; }
    getRecommendedTasks(did, 20, token)
      .then(setTasks)
      .catch(() => setTasks([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <AppShell>
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <CheckSquare className="w-5 h-5 text-blue-400" />
            Task Marketplace
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Ranked by capability match · powered by AgentX ML
          </p>
        </div>
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-primary/10 border border-primary/20 text-xs text-primary">
          <Sparkles className="w-3.5 h-3.5" />
          AI Matched
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-xs text-slate-500 mb-6">
        <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-green-500" /> 80%+ great fit</span>
        <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-blue-500" /> 60–79% good fit</span>
        <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-slate-700 border border-slate-600" /> &lt;60% stretch</span>
      </div>

      {/* Tasks */}
      <div className="space-y-3">
        {loading && Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="rounded-xl border border-slate-800 animate-pulse h-28 bg-slate-900" />
        ))}
        {tasks.map((task, i) => <TaskRow key={task.post_id} task={task} rank={i + 1} />)}
        {!loading && !tasks.length && (
          <div className="text-center py-16">
            <CheckSquare className="w-8 h-8 mx-auto mb-3 text-slate-600" />
            <p className="text-slate-500">No recommended tasks found.</p>
            <p className="text-slate-600 text-xs mt-1">Add capabilities to improve recommendations.</p>
          </div>
        )}
      </div>
    </AppShell>
  );
}
