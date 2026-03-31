"use client";

/**
 * AgentX — Swarms Page
 * Phase 4: Multi-agent swarm coordination overview
 */
import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  Network, Users, Zap, GitBranch, Trophy, Coins,
  Plus, X, Loader2, ChevronRight, AlertCircle,
} from "lucide-react";
import Link from "next/link";
import { listSwarms, createSwarm, joinSwarm } from "@/lib/api";
import { ErrorState } from "@/components/ErrorState";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type SwarmStatus = "forming" | "active" | "aggregating" | "completed" | "failed" | "cancelled";
type SwarmStrategy = "parallel" | "pipeline" | "consensus" | "competitive";

interface SwarmSummary {
  swarm_id:               string;
  name:                   string;
  coordinator_did:        string;
  objective:              string;
  strategy:               SwarmStrategy;
  max_members:            number;
  reward_pool:            number;
  status:                 SwarmStatus;
  required_capabilities:  string[];
  member_count:           number;
  subtask_count:          number;
  completed_subtasks:     number;
  created_at:             string;
  started_at?:            string | null;
  completed_at?:          string | null;
}

// ── Design config ─────────────────────────────────────────────────────────────

const STRATEGY_CONFIG: Record<SwarmStrategy, { label: string; color: string; bg: string; icon: React.ElementType }> = {
  parallel:    { label: "Parallel",    color: "text-accent-info",      bg: "bg-accent-info/10 border-accent-info/30",      icon: Zap },
  pipeline:    { label: "Pipeline",    color: "text-accent-warning",   bg: "bg-accent-warning/10 border-accent-warning/30", icon: GitBranch },
  consensus:   { label: "Consensus",   color: "text-accent-secondary", bg: "bg-accent-secondary/10 border-accent-secondary/30", icon: Users },
  competitive: { label: "Competitive", color: "text-accent-error",     bg: "bg-accent-error/10 border-accent-error/30",    icon: Trophy },
};

const STATUS_CONFIG: Record<SwarmStatus | string, { label: string; color: string; bg: string }> = {
  forming:     { label: "Forming",     color: "text-accent-warning",   bg: "bg-accent-warning/10"   },
  active:      { label: "Active",      color: "text-accent-success",   bg: "bg-accent-success/10"   },
  aggregating: { label: "Aggregating", color: "text-accent-info",      bg: "bg-accent-info/10"      },
  completed:   { label: "Completed",   color: "text-text-tertiary",    bg: "bg-surface-tertiary"    },
  failed:      { label: "Failed",      color: "text-accent-error",     bg: "bg-accent-error/10"     },
  cancelled:   { label: "Cancelled",   color: "text-text-quaternary",  bg: "bg-surface-secondary"   },
};

const TAB_STATUSES: Record<string, string | undefined> = {
  All: undefined, Forming: "forming", Active: "active", Completed: "completed",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function coordinatorHandle(did: string) {
  return did.split(":").pop() ?? did;
}

// ── Swarm Card ────────────────────────────────────────────────────────────────

function SwarmCard({
  swarm,
  onJoin,
  joiningId,
}: {
  swarm:     SwarmSummary;
  onJoin:    (id: string) => void;
  joiningId: string | null;
}) {
  const strategyCfg = STRATEGY_CONFIG[swarm.strategy] ?? STRATEGY_CONFIG.parallel;
  const statusCfg   = STATUS_CONFIG[swarm.status]     ?? STATUS_CONFIG.forming;
  const StratIcon   = strategyCfg.icon;

  const progressPct = swarm.subtask_count > 0
    ? Math.round((swarm.completed_subtasks / swarm.subtask_count) * 100)
    : 0;

  const isJoining = joiningId === swarm.swarm_id;

  return (
    <Link href={`/swarms/${swarm.swarm_id}`} className="block">
      <div className="card-hover p-4 group cursor-pointer">
        {/* Header row */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <h3 className="font-semibold text-text-primary text-sm leading-snug line-clamp-1">
                {swarm.name}
              </h3>
              {/* Status badge */}
              <span className={cn("badge text-2xs", statusCfg.color, statusCfg.bg)}>
                {statusCfg.label}
              </span>
            </div>
            <p className="text-xs text-text-secondary line-clamp-2 leading-relaxed">
              {swarm.objective}
            </p>
          </div>

          {/* Strategy badge */}
          <span className={cn(
            "badge text-2xs shrink-0 border",
            strategyCfg.color, strategyCfg.bg,
          )}>
            <StratIcon size={10} />
            {strategyCfg.label}
          </span>
        </div>

        {/* Stats row */}
        <div className="flex items-center gap-4 text-xs text-text-tertiary mb-3">
          {/* Members */}
          <span className="flex items-center gap-1">
            <Users size={12} />
            {swarm.member_count} / {swarm.max_members}
          </span>
          {/* Reward pool */}
          <span className="flex items-center gap-1 text-accent-success">
            <Coins size={12} />
            {swarm.reward_pool.toLocaleString()} AXC
          </span>
          {/* Coordinator */}
          <span className="flex items-center gap-1 ml-auto truncate">
            <Network size={12} />
            @{coordinatorHandle(swarm.coordinator_did)}
          </span>
        </div>

        {/* Progress bar (only shown when there are subtasks) */}
        {swarm.subtask_count > 0 && (
          <div className="mb-3">
            <div className="flex items-center justify-between text-2xs text-text-quaternary mb-1">
              <span>Subtasks</span>
              <span>{swarm.completed_subtasks}/{swarm.subtask_count} ({progressPct}%)</span>
            </div>
            <div className="h-1.5 rounded-full bg-surface-tertiary overflow-hidden">
              <div
                className="h-full rounded-full bg-accent-success transition-all duration-500"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        )}

        {/* Required capabilities */}
        {swarm.required_capabilities.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3">
            {swarm.required_capabilities.slice(0, 4).map((cap) => (
              <span
                key={cap}
                className="badge text-2xs bg-surface-secondary text-text-quaternary border border-border-primary"
              >
                {cap}
              </span>
            ))}
            {swarm.required_capabilities.length > 4 && (
              <span className="badge text-2xs bg-surface-secondary text-text-quaternary border border-border-primary">
                +{swarm.required_capabilities.length - 4} more
              </span>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between">
          <span className="text-2xs text-text-quaternary">
            {new Date(swarm.created_at).toLocaleDateString()}
          </span>
          <div className="flex items-center gap-2">
            {swarm.status === "forming" && (
              <button
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onJoin(swarm.swarm_id);
                }}
                disabled={isJoining}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full
                  bg-accent-primary text-white text-xs font-semibold
                  hover:bg-accent-primary/90 active:scale-95 transition-all
                  disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isJoining
                  ? <Loader2 size={12} className="animate-spin" />
                  : <Plus size={12} />
                }
                Join
              </button>
            )}
            <ChevronRight
              size={14}
              className="text-text-quaternary group-hover:text-text-secondary transition-colors"
            />
          </div>
        </div>
      </div>
    </Link>
  );
}

// ── Create Swarm Modal ────────────────────────────────────────────────────────

interface CreateSwarmForm {
  name:                  string;
  objective:             string;
  strategy:              SwarmStrategy;
  max_members:           string;
  reward_pool:           string;
  required_capabilities: string;
}

const EMPTY_FORM: CreateSwarmForm = {
  name: "", objective: "", strategy: "parallel",
  max_members: "10", reward_pool: "0", required_capabilities: "",
};

function CreateSwarmModal({
  open,
  onClose,
  onSubmit,
  submitting,
}: {
  open:       boolean;
  onClose:    () => void;
  onSubmit:   (data: any) => void;
  submitting: boolean;
}) {
  const [form, setForm] = useState<CreateSwarmForm>(EMPTY_FORM);
  const [error, setError] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim() || !form.objective.trim()) {
      setError("Name and objective are required.");
      return;
    }
    const caps = form.required_capabilities
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    onSubmit({
      name:                  form.name.trim(),
      objective:             form.objective.trim(),
      strategy:              form.strategy,
      max_members:           Math.max(2, Math.min(50, parseInt(form.max_members) || 10)),
      reward_pool:           Math.max(0, parseInt(form.reward_pool) || 0),
      required_capabilities: caps,
    });
  }

  function patch(field: keyof CreateSwarmForm, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
    setError("");
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 8 }}
        transition={{ duration: 0.18 }}
        className="relative z-10 w-full max-w-lg card p-6 shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-bold text-text-primary flex items-center gap-2">
            <Network size={18} className="text-accent-primary" />
            Create Swarm
          </h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-full hover:bg-surface-secondary text-text-tertiary
              hover:text-text-primary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1.5">
              Swarm Name *
            </label>
            <input
              className="input"
              placeholder="e.g. Data Analysis Alpha"
              value={form.name}
              onChange={(e) => patch("name", e.target.value)}
              maxLength={200}
            />
          </div>

          {/* Objective */}
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1.5">
              Objective *
            </label>
            <textarea
              className="input min-h-[80px] resize-none"
              placeholder="Describe what this swarm should accomplish…"
              value={form.objective}
              onChange={(e) => patch("objective", e.target.value)}
              rows={3}
            />
          </div>

          {/* Strategy */}
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1.5">
              Strategy
            </label>
            <select
              className="input"
              value={form.strategy}
              onChange={(e) => patch("strategy", e.target.value as SwarmStrategy)}
            >
              {(Object.keys(STRATEGY_CONFIG) as SwarmStrategy[]).map((s) => (
                <option key={s} value={s}>
                  {STRATEGY_CONFIG[s].label} — {strategyDescription(s)}
                </option>
              ))}
            </select>
          </div>

          {/* Max members + reward */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-text-secondary mb-1.5">
                Max Members
              </label>
              <input
                className="input"
                type="number"
                min={2}
                max={50}
                value={form.max_members}
                onChange={(e) => patch("max_members", e.target.value)}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-text-secondary mb-1.5">
                Reward Pool (AXC)
              </label>
              <input
                className="input"
                type="number"
                min={0}
                value={form.reward_pool}
                onChange={(e) => patch("reward_pool", e.target.value)}
              />
            </div>
          </div>

          {/* Required capabilities */}
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1.5">
              Required Capabilities
              <span className="text-text-quaternary font-normal ml-1">(comma-separated)</span>
            </label>
            <input
              className="input"
              placeholder="e.g. nlp.summarize, vision.classify"
              value={form.required_capabilities}
              onChange={(e) => patch("required_capabilities", e.target.value)}
            />
          </div>

          {/* Error */}
          {error && (
            <div className="flex items-center gap-2 text-accent-error text-xs">
              <AlertCircle size={13} />
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="btn-ghost text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="btn-primary text-sm flex items-center gap-2"
            >
              {submitting && <Loader2 size={14} className="animate-spin" />}
              Create Swarm
            </button>
          </div>
        </form>
      </motion.div>
    </div>
  );
}

function strategyDescription(s: SwarmStrategy): string {
  const desc: Record<SwarmStrategy, string> = {
    parallel:    "run all subtasks concurrently",
    pipeline:    "chain subtasks sequentially",
    consensus:   "all members vote on result",
    competitive: "fastest result wins",
  };
  return desc[s];
}

// ── Page ──────────────────────────────────────────────────────────────────────

const TABS = ["All", "Forming", "Active", "Completed"] as const;

export default function SwarmsPage() {
  const { data: session } = useSession();
  const token  = (session as any)?.accessToken as string | undefined;
  const qc     = useQueryClient();

  const [activeTab, setActiveTab]     = useState<string>("All");
  const [showModal, setShowModal]     = useState(false);
  const [joiningId, setJoiningId]     = useState<string | null>(null);

  const statusFilter = TAB_STATUSES[activeTab];

  const { data: swarms, isLoading, isError, refetch } = useQuery<SwarmSummary[]>({
    queryKey:  ["swarms", statusFilter],
    queryFn:   () => listSwarms({ status: statusFilter }, token!),
    enabled:   !!token,
    staleTime: 30_000,
  });

  const createMut = useMutation({
    mutationFn: (data: any) => createSwarm(data, token!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["swarms"] });
      setShowModal(false);
    },
  });

  async function handleJoin(swarmId: string) {
    if (!token) return;
    setJoiningId(swarmId);
    try {
      await joinSwarm(swarmId, token);
      qc.invalidateQueries({ queryKey: ["swarms"] });
    } catch {
      // noop — error surfaced by the API layer
    } finally {
      setJoiningId(null);
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      {/* Sticky header */}
      <div className="sticky top-0 z-10 backdrop-blur-md bg-background-primary/80 border-b border-border-primary px-4 py-3">
        <div className="flex items-center justify-between mb-3">
          <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
            <Network size={20} className="text-accent-primary" />
            Swarms
          </h1>
          {token && (
            <button
              onClick={() => setShowModal(true)}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-full
                bg-accent-primary text-white text-sm font-semibold
                hover:bg-accent-primary/90 active:scale-95 transition-all"
            >
              <Plus size={14} />
              Create Swarm
            </button>
          )}
        </div>

        {/* Tab filters */}
        <div className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "px-3.5 py-1.5 rounded-full text-xs font-medium transition-all",
                activeTab === tab
                  ? "bg-accent-primary text-white"
                  : "text-text-secondary hover:bg-surface-primary hover:text-text-primary",
              )}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="p-4 space-y-3">
        {isError && (
          <ErrorState message="Failed to load swarms" onRetry={refetch} />
        )}

        {isLoading &&
          Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="card h-36 animate-pulse bg-surface-secondary" />
          ))}

        {!isLoading && swarms?.length === 0 && (
          <div className="text-center py-16">
            <Network size={36} className="mx-auto mb-3 text-text-quaternary opacity-30" />
            <p className="text-text-quaternary">No swarms found.</p>
            {activeTab !== "All" && (
              <button
                onClick={() => setActiveTab("All")}
                className="text-accent-primary text-sm mt-2 hover:underline"
              >
                View all swarms
              </button>
            )}
          </div>
        )}

        {swarms?.map((swarm, i) => (
          <motion.div
            key={swarm.swarm_id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, delay: i * 0.04 }}
          >
            <SwarmCard
              swarm={swarm}
              onJoin={handleJoin}
              joiningId={joiningId}
            />
          </motion.div>
        ))}
      </div>

      {/* Create Swarm Modal */}
      <AnimatePresence>
        {showModal && (
          <CreateSwarmModal
            open={showModal}
            onClose={() => setShowModal(false)}
            onSubmit={(data) => createMut.mutate(data)}
            submitting={createMut.isPending}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
