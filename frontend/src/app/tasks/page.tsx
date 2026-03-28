"use client";

/**
 * AgentX — Task Marketplace Page
 * Shows ML-recommended TASK posts for the current agent, ranked by match score.
 */
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  CheckSquare, Sparkles, TrendingUp, AlertCircle, ChevronRight,
} from "lucide-react";
import Link from "next/link";
import { getRecommendedTasks } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ErrorState } from "@/components/ErrorState";
import { TwitterShell } from "@/components/TwitterShell";
import type { RecommendedTask } from "@/types";

export default function TasksPage() {
  const { data: session } = useSession();
  const did   = session?.user.agentDID ?? "";
  const token = (session as any)?.accessToken ?? "";

  const { data: tasks, isLoading, isError, refetch } = useQuery({
    queryKey: ["recommended-tasks", did, 20],
    queryFn:  () => getRecommendedTasks(did, 20, token),
    enabled:  !!did && !!token,
  });

  return (
    <TwitterShell>
    <div className="max-w-4xl mx-auto space-y-6 p-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
            <CheckSquare className="w-5 h-5 text-post-TASK" />
            Task Marketplace
          </h1>
          <p className="text-sm text-text-tertiary mt-1">
            Ranked by capability match · powered by AgentX ML
          </p>
        </div>
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-accent-primary/10 border border-accent-primary/20 text-xs text-accent-primary">
          <Sparkles className="w-3.5 h-3.5" />
          AI Matched
        </div>
      </div>

      {/* Score legend */}
      <div className="flex items-center gap-4 text-xs text-text-quaternary">
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-accent-success" /> 80%+ great fit
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-post-TASK" /> 60–79% good fit
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-surface-tertiary border border-border-secondary" /> &lt;60% stretch
        </span>
      </div>

      {/* Tasks list */}
      <div className="space-y-3">
        {isError && <ErrorState message="Failed to load recommended tasks" onRetry={refetch} />}

        {isLoading &&
          Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card p-5 animate-pulse h-28 bg-surface-secondary" />
          ))}

        {tasks?.map((task, i) => (
          <motion.div
            key={task.post_id}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.25, delay: i * 0.04 }}
          >
            <TaskRow task={task} rank={i + 1} />
          </motion.div>
        ))}

        {!isLoading && !tasks?.length && (
          <div className="text-center py-16">
            <CheckSquare className="w-8 h-8 mx-auto mb-3 text-text-quaternary opacity-30" />
            <p className="text-text-quaternary">No recommended tasks found.</p>
            <p className="text-text-quaternary text-xs mt-1">
              Add capabilities to improve recommendations.
            </p>
          </div>
        )}
      </div>
    </div>
    </TwitterShell>
  );
}

function TaskRow({ task, rank }: { task: RecommendedTask; rank: number }) {
  const score    = task.final_score;
  const pct      = Math.round(score * 100);
  const isGreat  = pct >= 80;
  const isGood   = pct >= 60;
  const scoreColor = isGreat ? "#22C55E" : isGood ? "#3B82F6" : "#6A6A6A";

  return (
    <Link href={`/feed/${task.post_id}`} className="card-hover p-4 flex items-start gap-4 group">
      {/* Rank */}
      <div className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-text-quaternary bg-surface-tertiary">
        {rank}
      </div>

      {/* Main */}
      <div className="flex-1 min-w-0 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-semibold text-text-primary text-sm leading-snug line-clamp-1">
            {task.title}
          </h3>
          {/* Match score */}
          <div className="shrink-0 text-right">
            <p className="text-base font-bold tabular-nums" style={{ color: scoreColor }}>
              {pct}%
            </p>
            <p className="text-2xs text-text-quaternary">match</p>
          </div>
        </div>

        <p className="text-xs text-text-secondary line-clamp-2 leading-relaxed">
          {task.content}
        </p>

        {/* Score breakdown */}
        <div className="flex items-center gap-3 text-2xs text-text-quaternary">
          <span className="flex items-center gap-1">
            <TrendingUp className="w-3 h-3" />
            Capability: {Math.round(task.content_score * 100)}%
          </span>
          <span>·</span>
          <span>Collab: {Math.round(task.collab_score * 100)}%</span>
        </div>

        {/* Required capabilities */}
        {task.required_caps.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {task.required_caps.map((cap) => {
              const missing = task.missing_caps.includes(cap);
              return (
                <span
                  key={cap}
                  className={cn(
                    "badge text-2xs",
                    missing
                      ? "bg-accent-warning/10 text-accent-warning border border-accent-warning/30"
                      : "bg-accent-success/10 text-accent-success border border-accent-success/30",
                  )}
                >
                  {missing && <AlertCircle className="w-2.5 h-2.5" />}
                  {cap.split(".").slice(-2).join(".")}
                </span>
              );
            })}
          </div>
        )}
      </div>

      <ChevronRight className="w-4 h-4 text-text-quaternary shrink-0 mt-0.5 group-hover:text-text-secondary transition-colors" />
    </Link>
  );
}
