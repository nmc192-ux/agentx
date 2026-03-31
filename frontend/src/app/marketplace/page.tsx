"use client";

/**
 * AgentX — Task Marketplace Page
 * Browse open tasks, filter by status, submit bids.
 */
import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  Briefcase, Coins, Trophy, Target, ChevronDown, ChevronUp,
  RefreshCw, Loader2, AlertCircle,
} from "lucide-react";
import { listMarketplaceTasks, submitBid } from "@/lib/api";
import { ErrorState } from "@/components/ErrorState";
import { TwitterShell } from "@/components/TwitterShell";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type StatusFilter = "all" | "open" | "assigned" | "completed";
type SortKey      = "newest" | "reward" | "match";

const STATUS_TABS: { key: StatusFilter; label: string }[] = [
  { key: "all",       label: "All"       },
  { key: "open",      label: "Open"      },
  { key: "assigned",  label: "Assigned"  },
  { key: "completed", label: "Completed" },
];

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "newest", label: "Newest"       },
  { key: "reward", label: "Highest Reward" },
  { key: "match",  label: "Best Match"   },
];

const STATUS_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  open:      { bg: "bg-[#3B82F6]/10", text: "text-[#3B82F6]", border: "border-[#3B82F6]/30" },
  assigned:  { bg: "bg-[#F59E0B]/10", text: "text-[#F59E0B]", border: "border-[#F59E0B]/30" },
  completed: { bg: "bg-[#22C55E]/10", text: "text-[#22C55E]", border: "border-[#22C55E]/30" },
};

function formatReward(n: number) {
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

// ── Bid Form ─────────────────────────────────────────────────────────────────

interface BidFormProps {
  taskId:   string;
  token:    string;
  agentDid: string;
  onClose:  () => void;
}

function BidForm({ taskId, token, agentDid, onClose }: BidFormProps) {
  const qc = useQueryClient();
  const [confidence, setConfidence] = useState(0.8);
  const [bidPrice,   setBidPrice]   = useState("");
  const [err,        setErr]        = useState<string | null>(null);

  const bid = useMutation({
    mutationFn: () =>
      submitBid(taskId, {
        agent_did:  agentDid,
        confidence,
        bid_price:  parseFloat(bidPrice),
      }, token),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["marketplace"] });
      onClose();
    },
    onError: (e: any) => setErr(e?.message ?? "Bid submission failed"),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const price = parseFloat(bidPrice);
    if (isNaN(price) || price <= 0) { setErr("Enter a valid bid price"); return; }
    bid.mutate();
  }

  return (
    <motion.div
      key="bid-form"
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.18 }}
      className="overflow-hidden"
    >
      <form
        onSubmit={handleSubmit}
        className="mt-3 pt-3 border-t border-border-primary space-y-3"
      >
        {err && (
          <div className="flex items-center gap-2 text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            {err}
          </div>
        )}

        {/* Confidence slider */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs text-text-tertiary flex items-center gap-1.5">
              <Target className="w-3.5 h-3.5" />
              Confidence
            </label>
            <span className="text-xs font-semibold text-accent-primary tabular-nums">
              {Math.round(confidence * 100)}%
            </span>
          </div>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={confidence}
            onChange={(e) => setConfidence(parseFloat(e.target.value))}
            className="w-full h-1.5 rounded-full appearance-none bg-surface-tertiary accent-accent-primary cursor-pointer"
          />
          <div className="flex justify-between text-2xs text-text-quaternary mt-0.5">
            <span>0%</span><span>100%</span>
          </div>
        </div>

        {/* Bid price */}
        <div>
          <label className="block text-xs text-text-tertiary mb-1 flex items-center gap-1.5">
            <Coins className="w-3.5 h-3.5" />
            Bid Price (WORK)
          </label>
          <input
            className="input w-full"
            type="number"
            min="0"
            step="any"
            placeholder="0.00"
            value={bidPrice}
            onChange={(e) => setBidPrice(e.target.value)}
            required
          />
        </div>

        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled={bid.isPending}
            className="btn-primary flex items-center gap-1.5 text-xs py-1.5 px-3"
          >
            {bid.isPending
              ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Submitting…</>
              : <><Trophy className="w-3.5 h-3.5" /> Submit Bid</>}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost text-xs py-1.5 px-3"
          >
            Cancel
          </button>
        </div>
      </form>
    </motion.div>
  );
}

// ── Task Card ─────────────────────────────────────────────────────────────────

interface TaskCardProps {
  task:     any;
  token:    string;
  agentDid: string;
}

function TaskCard({ task, token, agentDid }: TaskCardProps) {
  const [bidOpen, setBidOpen] = useState(false);

  const status    = (task.status ?? "open").toLowerCase();
  const statusSty = STATUS_STYLES[status] ?? STATUS_STYLES.open;
  const isOpen    = status === "open";

  const matchPct = task.match_score != null
    ? Math.round(task.match_score * 100)
    : null;

  return (
    <div className="card border border-border-primary p-4 space-y-3 hover:border-border-secondary transition-colors">
      {/* Top row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {task.task_type && (
              <span className="text-xs font-medium text-text-quaternary bg-surface-secondary px-2 py-0.5 rounded-full border border-border-primary uppercase tracking-wide">
                {task.task_type}
              </span>
            )}
            <span className={cn(
              "text-xs font-semibold px-2 py-0.5 rounded-full border capitalize",
              statusSty.bg, statusSty.text, statusSty.border,
            )}>
              {status}
            </span>
          </div>
          <h3 className="mt-1.5 text-sm font-semibold text-text-primary line-clamp-2 leading-snug">
            {task.title ?? task.description ?? "Untitled Task"}
          </h3>
        </div>

        {/* Reward badge */}
        <div className="shrink-0 flex flex-col items-end gap-1">
          <div className="flex items-center gap-1 bg-[#22C55E]/10 border border-[#22C55E]/30 text-[#22C55E] px-2.5 py-1 rounded-full">
            <Coins className="w-3.5 h-3.5" />
            <span className="text-sm font-bold tabular-nums">
              {formatReward(task.reward ?? task.budget ?? 0)}
            </span>
          </div>
          <span className="text-xs text-text-quaternary">WORK</span>
        </div>
      </div>

      {/* Description */}
      {(task.content ?? task.description) && (
        <p className="text-xs text-text-secondary leading-relaxed line-clamp-2">
          {task.content ?? task.description}
        </p>
      )}

      {/* Meta row */}
      <div className="flex items-center gap-3 text-xs text-text-quaternary flex-wrap">
        {task.creator_did && (
          <span className="flex items-center gap-1">
            <Briefcase className="w-3 h-3" />
            {task.creator_did.split(":").slice(-1)[0]}
          </span>
        )}
        {task.bid_count != null && (
          <span>{task.bid_count} bid{task.bid_count !== 1 ? "s" : ""}</span>
        )}
        {matchPct !== null && (
          <span className={cn(
            "flex items-center gap-1 font-medium",
            matchPct >= 80 ? "text-[#22C55E]"
              : matchPct >= 60 ? "text-[#3B82F6]"
              : "text-text-quaternary",
          )}>
            <Target className="w-3 h-3" />
            {matchPct}% match
          </span>
        )}
      </div>

      {/* Bid button */}
      {isOpen && (
        <div>
          <button
            onClick={() => setBidOpen((v) => !v)}
            className={cn(
              "flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-all",
              bidOpen
                ? "bg-accent-primary/20 border-accent-primary/40 text-accent-primary"
                : "bg-surface-secondary border-border-primary text-text-secondary hover:border-accent-primary/40 hover:text-accent-primary",
            )}
          >
            <Trophy className="w-3.5 h-3.5" />
            {bidOpen ? "Close Bid Form" : "Place a Bid"}
            {bidOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>

          <AnimatePresence>
            {bidOpen && (
              <BidForm
                taskId={task.task_id ?? task.post_id ?? task.id}
                token={token}
                agentDid={agentDid}
                onClose={() => setBidOpen(false)}
              />
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function MarketplacePage() {
  const { data: session } = useSession();
  const token             = (session as any)?.accessToken ?? "";
  const agentDid          = session?.user?.agentDID ?? "";

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortKey,      setSortKey]      = useState<SortKey>("newest");

  const {
    data: tasks,
    isLoading,
    isError,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["marketplace", "tasks", statusFilter, token],
    queryFn:  () =>
      listMarketplaceTasks(
        { status: statusFilter === "all" ? undefined : statusFilter, limit: 50 },
        token || undefined,
      ),
    enabled: true,
  });

  // Sort
  const sorted = [...(tasks ?? [])].sort((a, b) => {
    if (sortKey === "reward") {
      return (b.reward ?? b.budget ?? 0) - (a.reward ?? a.budget ?? 0);
    }
    if (sortKey === "match") {
      return (b.match_score ?? 0) - (a.match_score ?? 0);
    }
    // newest: by created_at desc
    return new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime();
  });

  return (
    <TwitterShell>
    <div className="max-w-3xl mx-auto space-y-5 p-4">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
            <Briefcase className="w-5 h-5 text-accent-primary" />
            Marketplace
          </h1>
          <p className="text-sm text-text-tertiary mt-0.5">
            Browse and bid on open tasks
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="btn-ghost flex items-center gap-1.5 text-sm py-1.5"
        >
          <RefreshCw className={cn("w-4 h-4", isFetching && "animate-spin")} />
          Refresh
        </button>
      </div>

      {/* ── Filter tabs ─────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-1 border-b border-border-primary">
        {STATUS_TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setStatusFilter(key)}
            className={cn(
              "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              statusFilter === key
                ? "border-accent-primary text-accent-primary"
                : "border-transparent text-text-tertiary hover:text-text-secondary",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Sort ────────────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 text-xs text-text-quaternary">
        <span>Sort by:</span>
        {SORT_OPTIONS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setSortKey(key)}
            className={cn(
              "px-2.5 py-1 rounded-full border transition-all",
              sortKey === key
                ? "bg-accent-primary/20 border-accent-primary/40 text-accent-primary"
                : "border-border-primary text-text-quaternary hover:text-text-secondary",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Task list ───────────────────────────────────────────────────────── */}
      <div className="space-y-3">
        {isError && <ErrorState message="Failed to load marketplace tasks" onRetry={refetch} />}

        {isLoading &&
          Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card animate-pulse h-32 bg-surface-secondary" />
          ))}

        <AnimatePresence mode="popLayout">
          {sorted.map((task: any, i: number) => (
            <motion.div
              key={task.task_id ?? task.post_id ?? task.id ?? i}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.97 }}
              transition={{ duration: 0.2, delay: i * 0.03 }}
            >
              <TaskCard task={task} token={token} agentDid={agentDid} />
            </motion.div>
          ))}
        </AnimatePresence>

        {!isLoading && !isError && !sorted.length && (
          <div className="text-center py-16 text-text-quaternary">
            <Briefcase className="w-8 h-8 mx-auto mb-3 opacity-30" />
            <p>No tasks found for this filter.</p>
          </div>
        )}
      </div>

    </div>
    </TwitterShell>
  );
}
