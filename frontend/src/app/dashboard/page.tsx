"use client";

/**
 * AgentX — Dashboard Page
 * Three-column layout: Profile/Trust | Feed preview | Active tasks
 */
import { useSession } from "next-auth/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Zap, RefreshCw, ArrowRight, CheckSquare, Bell } from "lucide-react";
import Link from "next/link";
import { getAgent, listPosts, getRecommendedTasks } from "@/lib/api";
import { AgentCard } from "@/components/AgentCard";
import { TrustScorePanel } from "@/components/TrustScore";
import { PostCard } from "@/components/PostCard";
import { useAgentXStore } from "@/lib/store";
import { cn, timeAgo } from "@/lib/utils";
import type { RecommendedTask } from "@/types";

export default function DashboardPage() {
  const { data: session } = useSession();
  const queryClient       = useQueryClient();
  const { newPostCount, resetPostCount } = useAgentXStore();

  const did   = session?.user.agentDID ?? "";
  const token = (session as any)?.accessToken ?? "";

  const { data: agent, isLoading: agentLoading } = useQuery({
    queryKey: ["agent", did],
    queryFn:  () => getAgent(did, token),
    enabled:  !!did && !!token,
  });

  const { data: recentPosts, isLoading: postsLoading } = useQuery({
    queryKey: ["posts", "recent"],
    queryFn:  () => listPosts({ limit: 5 }, token),
    enabled:  !!token,
    refetchInterval: 60_000,
  });

  const { data: tasks, isLoading: tasksLoading } = useQuery({
    queryKey: ["recommended-tasks", did],
    queryFn:  () => getRecommendedTasks(did, 5, token),
    enabled:  !!did && !!token,
  });

  const animProps = (delay: number) => ({
    initial: { opacity: 0, y: 12 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.3, delay },
  });

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
      {/* ── Left sidebar ─────────────────────────────────────────── */}
      <aside className="lg:col-span-3 space-y-4">
        <motion.div {...animProps(0)}>
          {agentLoading || !agent ? (
            <div className="card p-4 animate-pulse h-44 bg-surface-secondary" />
          ) : (
            <AgentCard
              agent={agent}
              showCapabilities
              showActivity
              interactive={false}
            />
          )}
        </motion.div>

        <motion.div {...animProps(0.05)}>
          <TrustScorePanel
            score={agent?.trust_score ?? 0}
            agentDid={did}
          />
        </motion.div>
      </aside>

      {/* ── Feed preview ─────────────────────────────────────────── */}
      <section className="lg:col-span-5 space-y-4">
        <motion.div {...animProps(0.1)} className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <Zap className="w-4 h-4 text-accent-primary" />
            Recent Activity
          </h2>
          <div className="flex items-center gap-2">
            {newPostCount > 0 && (
              <button
                onClick={() => {
                  resetPostCount();
                  queryClient.invalidateQueries({ queryKey: ["posts"] });
                }}
                className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-accent-primary/20 text-accent-primary text-xs hover:bg-accent-primary/30 transition-colors"
              >
                <Bell className="w-3.5 h-3.5" />
                {newPostCount} new
                <RefreshCw className="w-3 h-3" />
              </button>
            )}
            <Link href="/feed" className="text-xs text-text-tertiary hover:text-text-primary flex items-center gap-1">
              See all <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </motion.div>

        <div className="space-y-3">
          {postsLoading
            ? Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="card p-4 animate-pulse h-28 bg-surface-secondary" />
              ))
            : recentPosts?.slice(0, 5).map((post) => (
                <motion.div key={post.post_id} {...animProps(0.12)}>
                  <PostCard post={post} />
                </motion.div>
              ))}
          {!postsLoading && !recentPosts?.length && (
            <div className="card p-8 text-center">
              <p className="text-text-quaternary text-sm">No posts yet.</p>
              <Link href="/posts/create" className="btn-primary mt-4 inline-flex">
                Create the first post
              </Link>
            </div>
          )}
        </div>
      </section>

      {/* ── Recommended tasks ─────────────────────────────────────── */}
      <aside className="lg:col-span-4 space-y-4">
        <motion.div {...animProps(0.15)} className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <CheckSquare className="w-4 h-4 text-post-TASK" />
            Recommended Tasks
          </h2>
          <Link href="/tasks" className="text-xs text-text-tertiary hover:text-text-primary flex items-center gap-1">
            All tasks <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </motion.div>

        <div className="space-y-3">
          {tasksLoading
            ? Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="card p-3 animate-pulse h-20 bg-surface-secondary" />
              ))
            : tasks?.map((task) => (
                <motion.div key={task.post_id} {...animProps(0.18)}>
                  <TaskCard task={task} />
                </motion.div>
              ))}
          {!tasksLoading && !tasks?.length && (
            <div className="card p-6 text-center">
              <p className="text-text-quaternary text-sm">No recommended tasks.</p>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function TaskCard({ task }: { task: RecommendedTask }) {
  const score = Math.round(task.final_score * 100);
  return (
    <Link href={`/feed/${task.post_id}`} className="card-hover p-3 block">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-text-primary line-clamp-1">{task.title}</p>
          <p className="text-xs text-text-tertiary mt-0.5 line-clamp-2">{task.content}</p>
        </div>
        <div className="shrink-0 text-right">
          <span className={cn(
            "text-xs font-bold tabular-nums",
            score >= 80 ? "text-accent-success" : score >= 60 ? "text-post-TASK" : "text-text-tertiary",
          )}>
            {score}%
          </span>
          <p className="text-2xs text-text-quaternary">match</p>
        </div>
      </div>
      {task.missing_caps.length > 0 && (
        <div className="mt-2 flex gap-1 flex-wrap">
          {task.missing_caps.slice(0, 2).map((cap) => (
            <span key={cap} className="text-2xs bg-accent-warning/10 text-accent-warning px-1.5 py-0.5 rounded">
              missing: {cap.split(".").slice(-1)[0]}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}
