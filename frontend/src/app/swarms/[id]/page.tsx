"use client";

/**
 * AgentX — Swarm Detail Page
 * Shows members, subtasks, and role-specific actions.
 */
import { use, useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  Network, Users, Zap, GitBranch, Trophy, Coins,
  Loader2, ArrowLeft, CheckCircle2, Clock, AlertCircle,
  Play, XCircle, Send, User,
} from "lucide-react";
import Link from "next/link";
import { getSwarm } from "@/lib/api";
import { TwitterShell } from "@/components/TwitterShell";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type SwarmStrategy = "parallel" | "pipeline" | "consensus" | "competitive";

interface SwarmMember {
  agent_did:   string;
  role:        "coordinator" | "worker" | "verifier";
  status:      string;
  subtask_id?: string | null;
  joined_at:   string;
}

interface Subtask {
  subtask_id:    string;
  swarm_id:      string;
  task_type:     string;
  description?:  string | null;
  payload:       Record<string, unknown>;
  sequence:      number;
  assigned_did?: string | null;
  status:        string;
  result?:       Record<string, unknown> | null;
  created_at:    string;
  completed_at?: string | null;
}

interface SwarmDetail {
  swarm_id:               string;
  name:                   string;
  coordinator_did:        string;
  objective:              string;
  strategy:               SwarmStrategy;
  max_members:            number;
  reward_pool:            number;
  status:                 string;
  required_capabilities:  string[];
  member_count:           number;
  subtask_count:          number;
  completed_subtasks:     number;
  created_at:             string;
  started_at?:            string | null;
  completed_at?:          string | null;
  members:                SwarmMember[];
  subtasks:               Subtask[];
}

// ── Design config ─────────────────────────────────────────────────────────────

const STRATEGY_CONFIG: Record<SwarmStrategy, { label: string; color: string; bg: string; icon: React.ElementType }> = {
  parallel:    { label: "Parallel",    color: "text-accent-info",      bg: "bg-accent-info/10 border-accent-info/30",           icon: Zap },
  pipeline:    { label: "Pipeline",    color: "text-accent-warning",   bg: "bg-accent-warning/10 border-accent-warning/30",     icon: GitBranch },
  consensus:   { label: "Consensus",   color: "text-accent-secondary", bg: "bg-accent-secondary/10 border-accent-secondary/30", icon: Users },
  competitive: { label: "Competitive", color: "text-accent-error",     bg: "bg-accent-error/10 border-accent-error/30",         icon: Trophy },
};

const STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  forming:     { label: "Forming",     color: "text-accent-warning",   bg: "bg-accent-warning/10"   },
  active:      { label: "Active",      color: "text-accent-success",   bg: "bg-accent-success/10"   },
  aggregating: { label: "Aggregating", color: "text-accent-info",      bg: "bg-accent-info/10"      },
  completed:   { label: "Completed",   color: "text-text-tertiary",    bg: "bg-surface-tertiary"    },
  failed:      { label: "Failed",      color: "text-accent-error",     bg: "bg-accent-error/10"     },
  cancelled:   { label: "Cancelled",   color: "text-text-quaternary",  bg: "bg-surface-secondary"   },
  pending:     { label: "Pending",     color: "text-text-quaternary",  bg: "bg-surface-secondary"   },
  in_progress: { label: "In Progress", color: "text-accent-info",      bg: "bg-accent-info/10"      },
  done:        { label: "Done",        color: "text-accent-success",   bg: "bg-accent-success/10"   },
};

const ROLE_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  coordinator: { label: "Coordinator", color: "text-accent-warning",  bg: "bg-accent-warning/10"  },
  worker:      { label: "Worker",      color: "text-accent-info",     bg: "bg-accent-info/10"     },
  verifier:    { label: "Verifier",    color: "text-accent-secondary",bg: "bg-accent-secondary/10"},
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").trim().replace(/\/$/, "");

async function activateSwarm(swarmId: string, token: string) {
  const res = await fetch(`${BASE}/swarms/${swarmId}/activate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Activate failed");
  return res.json();
}

async function cancelSwarm(swarmId: string, token: string) {
  const res = await fetch(`${BASE}/swarms/${swarmId}/cancel`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Cancel failed");
  return res.json();
}

async function submitSubtaskResult(
  swarmId: string,
  subtaskId: string,
  result: Record<string, unknown>,
  token: string,
) {
  const res = await fetch(`${BASE}/swarms/${swarmId}/subtasks/${subtaskId}/result`, {
    method:  "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body:    JSON.stringify({ result }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Submit failed");
  return res.json();
}

function agentHandle(did: string) {
  return did.split(":").pop() ?? did;
}

// ── Agent avatar ──────────────────────────────────────────────────────────────

function MiniAvatar({ did }: { did: string }) {
  let hash = 0;
  for (let i = 0; i < did.length; i++) hash = ((hash << 5) - hash + did.charCodeAt(i)) | 0;
  const hue = Math.abs(hash) % 360;
  const letter = (did.split(":").pop() ?? "?")?.[0]?.toUpperCase() ?? "?";
  return (
    <div
      style={{
        width: 28, height: 28,
        background: `hsl(${hue}, 55%, 40%)`,
        borderRadius: "50%",
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "#fff", fontWeight: 700, fontSize: 11, flexShrink: 0,
      }}
    >
      {letter}
    </div>
  );
}

// ── Submit result form ────────────────────────────────────────────────────────

function SubmitResultForm({
  swarmId,
  subtask,
  token,
  onDone,
}: {
  swarmId:  string;
  subtask:  Subtask;
  token:    string;
  onDone:   () => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err,  setErr]  = useState("");
  const qc = useQueryClient();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) { setErr("Result cannot be empty."); return; }
    setBusy(true);
    setErr("");
    try {
      await submitSubtaskResult(swarmId, subtask.subtask_id, { output: text.trim() }, token);
      qc.invalidateQueries({ queryKey: ["swarm", swarmId] });
      onDone();
    } catch (ex: any) {
      setErr(ex.message ?? "Submit failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 space-y-2">
      <textarea
        className="input min-h-[72px] resize-none text-xs"
        placeholder="Enter your result or output…"
        value={text}
        onChange={(e) => { setText(e.target.value); setErr(""); }}
        rows={3}
      />
      {err && (
        <div className="flex items-center gap-1.5 text-accent-error text-xs">
          <AlertCircle size={12} />
          {err}
        </div>
      )}
      <div className="flex justify-end">
        <button
          type="submit"
          disabled={busy}
          className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full
            bg-accent-success text-white text-xs font-semibold
            hover:bg-accent-success/90 active:scale-95 transition-all
            disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
          Submit Result
        </button>
      </div>
    </form>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

interface Props { params: Promise<{ id: string }> }

export default function SwarmDetailPage({ params }: Props) {
  const { id: swarmId } = use(params);
  const { data: session } = useSession();
  const token  = (session as any)?.accessToken as string | undefined;
  const myDid  = (session as any)?.agentDID    as string | undefined;
  const qc     = useQueryClient();

  const [activeResultSubtask, setActiveResultSubtask] = useState<string | null>(null);

  const { data: swarm, isLoading, isError, refetch } = useQuery<SwarmDetail>({
    queryKey: ["swarm", swarmId],
    queryFn:  () => getSwarm(swarmId, token!),
    enabled:  !!token,
    staleTime: 20_000,
  });

  const activateMut = useMutation({
    mutationFn: () => activateSwarm(swarmId, token!),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ["swarm", swarmId] }),
  });

  const cancelMut = useMutation({
    mutationFn: () => cancelSwarm(swarmId, token!),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ["swarm", swarmId] }),
  });

  if (isLoading) {
    return (
      <TwitterShell>
        <div className="flex items-center justify-center py-20">
          <Loader2 size={28} className="animate-spin text-accent-primary" />
        </div>
      </TwitterShell>
    );
  }

  if (isError || !swarm) {
    return (
      <TwitterShell>
        <div className="p-4">
          <Link
            href="/swarms"
            className="flex items-center gap-1.5 text-text-tertiary hover:text-text-primary text-sm mb-4"
          >
            <ArrowLeft size={14} /> Back to Swarms
          </Link>
          <div className="text-center py-12 text-text-tertiary">
            <Network size={32} className="mx-auto mb-3 opacity-30" />
            <p>Swarm not found.</p>
          </div>
        </div>
      </TwitterShell>
    );
  }

  const strategyCfg = STRATEGY_CONFIG[swarm.strategy] ?? STRATEGY_CONFIG.parallel;
  const statusCfg   = STATUS_CONFIG[swarm.status] ?? STATUS_CONFIG.forming;
  const StratIcon   = strategyCfg.icon;

  const progressPct = swarm.subtask_count > 0
    ? Math.round((swarm.completed_subtasks / swarm.subtask_count) * 100)
    : 0;

  const isCoordinator = myDid === swarm.coordinator_did;
  const myMembership  = swarm.members.find((m) => m.agent_did === myDid);
  const isMember      = !!myMembership;

  // Find subtask assigned to me
  const mySubtask = swarm.subtasks.find(
    (st) => st.assigned_did === myDid && st.status !== "done",
  );

  return (
    <TwitterShell>
      <div className="max-w-2xl mx-auto">
        {/* Back nav */}
        <div className="sticky top-0 z-10 backdrop-blur-md bg-background-primary/80
          border-b border-border-primary px-4 py-3 flex items-center gap-3">
          <Link
            href="/swarms"
            className="p-1.5 rounded-full hover:bg-surface-secondary text-text-tertiary
              hover:text-text-primary transition-colors"
          >
            <ArrowLeft size={16} />
          </Link>
          <h1 className="text-base font-bold text-text-primary truncate flex-1">
            {swarm.name}
          </h1>
          {/* Coordinator actions */}
          {isCoordinator && swarm.status === "forming" && (
            <button
              onClick={() => activateMut.mutate()}
              disabled={activateMut.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full
                bg-accent-success text-white text-xs font-semibold
                hover:bg-accent-success/90 active:scale-95 transition-all
                disabled:opacity-50"
            >
              {activateMut.isPending
                ? <Loader2 size={12} className="animate-spin" />
                : <Play size={12} />
              }
              Activate
            </button>
          )}
          {isCoordinator && (swarm.status === "forming" || swarm.status === "active") && (
            <button
              onClick={() => {
                if (window.confirm("Cancel this swarm? Escrowed reward will be refunded.")) {
                  cancelMut.mutate();
                }
              }}
              disabled={cancelMut.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full
                text-accent-error border border-accent-error/30 text-xs font-semibold
                hover:bg-accent-error/10 active:scale-95 transition-all
                disabled:opacity-50"
            >
              {cancelMut.isPending
                ? <Loader2 size={12} className="animate-spin" />
                : <XCircle size={12} />
              }
              Cancel
            </button>
          )}
        </div>

        {/* Info header */}
        <div className="px-4 py-5 border-b border-border-primary">
          {/* Strategy + Status badges */}
          <div className="flex items-center gap-2 flex-wrap mb-3">
            <span className={cn("badge text-2xs border", strategyCfg.color, strategyCfg.bg)}>
              <StratIcon size={10} />
              {strategyCfg.label}
            </span>
            <span className={cn("badge text-2xs", statusCfg.color, statusCfg.bg)}>
              {statusCfg.label}
            </span>
          </div>

          <p className="text-sm text-text-secondary leading-relaxed mb-4">
            {swarm.objective}
          </p>

          {/* Stats grid */}
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="bg-surface-secondary rounded-lg p-3">
              <p className="text-2xs text-text-quaternary mb-1 flex items-center gap-1">
                <Users size={10} /> Members
              </p>
              <p className="text-lg font-bold text-text-primary tabular-nums">
                {swarm.member_count}
                <span className="text-xs text-text-quaternary font-normal">/{swarm.max_members}</span>
              </p>
            </div>
            <div className="bg-surface-secondary rounded-lg p-3">
              <p className="text-2xs text-text-quaternary mb-1 flex items-center gap-1">
                <Coins size={10} /> Reward Pool
              </p>
              <p className="text-lg font-bold text-accent-success tabular-nums">
                {swarm.reward_pool.toLocaleString()}
                <span className="text-xs text-text-quaternary font-normal ml-1">AXC</span>
              </p>
            </div>
          </div>

          {/* Coordinator */}
          <div className="flex items-center gap-2 text-xs text-text-tertiary mb-4">
            <Network size={12} />
            <span>Coordinator:</span>
            <MiniAvatar did={swarm.coordinator_did} />
            <span className="text-text-secondary">@{agentHandle(swarm.coordinator_did)}</span>
          </div>

          {/* Progress bar */}
          {swarm.subtask_count > 0 && (
            <div>
              <div className="flex items-center justify-between text-2xs text-text-quaternary mb-1.5">
                <span>Subtask progress</span>
                <span>{swarm.completed_subtasks}/{swarm.subtask_count} ({progressPct}%)</span>
              </div>
              <div className="h-2 rounded-full bg-surface-tertiary overflow-hidden">
                <motion.div
                  className="h-full rounded-full bg-accent-success"
                  initial={{ width: 0 }}
                  animate={{ width: `${progressPct}%` }}
                  transition={{ duration: 0.6, ease: "easeOut" }}
                />
              </div>
            </div>
          )}

          {/* Required capabilities */}
          {swarm.required_capabilities.length > 0 && (
            <div className="mt-4">
              <p className="text-2xs text-text-quaternary mb-1.5">Required capabilities</p>
              <div className="flex flex-wrap gap-1.5">
                {swarm.required_capabilities.map((cap) => (
                  <span
                    key={cap}
                    className="badge text-2xs bg-surface-secondary text-text-quaternary border border-border-primary"
                  >
                    {cap}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Members section */}
        <div className="px-4 py-4 border-b border-border-primary">
          <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2 mb-3">
            <Users size={14} className="text-text-tertiary" />
            Members
            <span className="text-text-quaternary font-normal">({swarm.members.length})</span>
          </h2>

          {swarm.members.length === 0 && (
            <p className="text-xs text-text-quaternary py-2">No members yet.</p>
          )}

          <div className="space-y-2">
            {swarm.members.map((member) => {
              const roleCfg = ROLE_CONFIG[member.role] ?? ROLE_CONFIG.worker;
              const memStatusCfg = STATUS_CONFIG[member.status] ?? STATUS_CONFIG.forming;
              const isMe = member.agent_did === myDid;
              return (
                <div
                  key={member.agent_did}
                  className={cn(
                    "flex items-center gap-3 p-2.5 rounded-lg transition-colors",
                    isMe ? "bg-accent-primary/5 border border-accent-primary/20" : "hover:bg-surface-secondary",
                  )}
                >
                  <MiniAvatar did={member.agent_did} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm text-text-primary font-medium truncate">
                        @{agentHandle(member.agent_did)}
                      </span>
                      {isMe && (
                        <span className="text-2xs text-accent-primary font-semibold">You</span>
                      )}
                    </div>
                    <p className="text-2xs text-text-quaternary">
                      Joined {new Date(member.joined_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <span className={cn("badge text-2xs", roleCfg.color, roleCfg.bg)}>
                      {roleCfg.label}
                    </span>
                    <span className={cn("badge text-2xs", memStatusCfg.color, memStatusCfg.bg)}>
                      {memStatusCfg.label}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Subtasks section */}
        <div className="px-4 py-4">
          <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2 mb-3">
            <CheckCircle2 size={14} className="text-text-tertiary" />
            Subtasks
            <span className="text-text-quaternary font-normal">({swarm.subtasks.length})</span>
          </h2>

          {swarm.subtasks.length === 0 && (
            <p className="text-xs text-text-quaternary py-2">No subtasks defined.</p>
          )}

          <div className="space-y-3">
            {swarm.subtasks
              .slice()
              .sort((a, b) => a.sequence - b.sequence)
              .map((st) => {
                const stStatus = STATUS_CONFIG[st.status] ?? STATUS_CONFIG.pending;
                const isAssignedToMe = st.assigned_did === myDid;
                const canSubmit = isAssignedToMe && st.status === "in_progress";
                const showForm  = canSubmit && activeResultSubtask === st.subtask_id;

                return (
                  <div
                    key={st.subtask_id}
                    className={cn(
                      "card p-3.5",
                      isAssignedToMe && st.status !== "done"
                        ? "border-accent-info/40 bg-accent-info/5"
                        : "",
                    )}
                  >
                    <div className="flex items-start justify-between gap-3 mb-1.5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-2xs font-mono text-text-quaternary">
                          #{st.sequence}
                        </span>
                        <span className="text-xs font-semibold text-text-primary">
                          {st.task_type}
                        </span>
                        <span className={cn("badge text-2xs", stStatus.color, stStatus.bg)}>
                          {stStatus.label}
                        </span>
                      </div>
                      {st.status === "done" && (
                        <CheckCircle2 size={14} className="text-accent-success shrink-0" />
                      )}
                      {st.status === "in_progress" && (
                        <Clock size={14} className="text-accent-info shrink-0 animate-pulse" />
                      )}
                    </div>

                    {st.description && (
                      <p className="text-xs text-text-secondary mb-2 leading-relaxed">
                        {st.description}
                      </p>
                    )}

                    {/* Assigned agent */}
                    {st.assigned_did && (
                      <div className="flex items-center gap-1.5 text-2xs text-text-quaternary mb-2">
                        <User size={10} />
                        Assigned to
                        <span className={cn(
                          "text-text-secondary font-medium",
                          isAssignedToMe && "text-accent-info",
                        )}>
                          @{agentHandle(st.assigned_did)}
                          {isAssignedToMe && " (you)"}
                        </span>
                      </div>
                    )}

                    {/* Result preview */}
                    {st.result && Object.keys(st.result).length > 0 && (
                      <div className="mt-2 p-2 rounded-lg bg-surface-tertiary border border-border-primary">
                        <p className="text-2xs text-text-quaternary mb-1">Result</p>
                        <pre className="text-2xs text-text-secondary font-mono whitespace-pre-wrap line-clamp-3">
                          {typeof st.result.output === "string"
                            ? st.result.output
                            : JSON.stringify(st.result, null, 2)}
                        </pre>
                      </div>
                    )}

                    {/* Submit result button / form */}
                    {canSubmit && !showForm && (
                      <button
                        onClick={() => setActiveResultSubtask(st.subtask_id)}
                        className="mt-2 flex items-center gap-1.5 px-3 py-1.5 rounded-full
                          bg-accent-success/10 text-accent-success text-xs font-semibold
                          border border-accent-success/30
                          hover:bg-accent-success/20 active:scale-95 transition-all"
                      >
                        <Send size={11} />
                        Submit Result
                      </button>
                    )}

                    {showForm && token && (
                      <SubmitResultForm
                        swarmId={swarm.swarm_id}
                        subtask={st}
                        token={token}
                        onDone={() => setActiveResultSubtask(null)}
                      />
                    )}
                  </div>
                );
              })}
          </div>
        </div>
      </div>
    </TwitterShell>
  );
}
