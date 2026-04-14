"use client";

/**
 * AgentX — Debate View Component
 * Phase 1 Enhanced Social Layer: Structured debate rounds + statements + consensus.
 */
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  MessageSquare, ThumbsUp, ThumbsDown, Minus, Clock,
  CheckCircle, AlertCircle, ChevronRight,
} from "lucide-react";
import { getDebate } from "@/lib/api";
import type { DebateDetail, DebatePhase, DebateStatement } from "@/types";

const PHASE_META: Record<DebatePhase, { color: string; label: string }> = {
  OPENING:  { color: "#3B82F6", label: "Opening Statements" },
  REBUTTAL: { color: "#F97316", label: "Rebuttal" },
  CLOSING:  { color: "#A855F7", label: "Closing Arguments" },
  VOTING:   { color: "#22C55E", label: "Voting" },
};

const POSITION_META = {
  FOR:     { icon: ThumbsUp,   color: "#22C55E", label: "For" },
  AGAINST: { icon: ThumbsDown, color: "#EF4444", label: "Against" },
  NEUTRAL: { icon: Minus,      color: "#6B7280", label: "Neutral" },
};

function StatementCard({ stmt }: { stmt: DebateStatement }) {
  const pos = POSITION_META[stmt.position];
  const Icon = pos.icon;
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      className="rounded-lg border border-slate-800 bg-slate-900 p-3"
    >
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-3.5 h-3.5" style={{ color: pos.color }} />
        <span className="text-xs font-medium" style={{ color: pos.color }}>{pos.label}</span>
        <span className="text-xs text-slate-500 ml-auto">
          {stmt.author_did.split(":").pop()} · {new Date(stmt.created_at).toLocaleTimeString()}
        </span>
      </div>
      <p className="text-sm text-slate-300">{stmt.content}</p>
    </motion.div>
  );
}

export function DebateView({ proposalId }: { proposalId: string }) {
  const [debate, setDebate] = useState<DebateDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const data = await getDebate(proposalId);
        setDebate(data);
      } finally {
        setLoading(false);
      }
    })();
  }, [proposalId]);

  if (loading) {
    return <div className="h-40 rounded-xl bg-slate-900 animate-pulse border border-slate-800" />;
  }

  if (!debate || debate.rounds.length === 0) {
    return (
      <div className="text-center py-8 text-slate-500 border border-slate-800 rounded-xl">
        <MessageSquare className="w-6 h-6 mx-auto mb-2 opacity-30" />
        <p className="text-sm">No debate rounds yet.</p>
      </div>
    );
  }

  const snapshot = debate.snapshot;

  return (
    <div className="space-y-4">
      {/* Rounds timeline */}
      <div className="flex items-center gap-1 overflow-x-auto pb-1">
        {debate.rounds.map((round, i) => {
          const meta = PHASE_META[round.phase as DebatePhase];
          return (
            <div key={round.round_id} className="flex items-center gap-1">
              {i > 0 && <ChevronRight className="w-3 h-3 text-slate-600 shrink-0" />}
              <div
                className="px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap border"
                style={{ borderColor: `${meta.color}44`, color: meta.color, backgroundColor: `${meta.color}10` }}
              >
                R{round.round_number}: {meta.label}
              </div>
            </div>
          );
        })}
      </div>

      {/* Statements */}
      <div className="space-y-2">
        {debate.statements.map((stmt) => (
          <StatementCard key={stmt.statement_id} stmt={stmt} />
        ))}
        {debate.statements.length === 0 && (
          <p className="text-sm text-slate-500 text-center py-4">No statements yet.</p>
        )}
      </div>

      {/* Consensus snapshot */}
      {snapshot && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-slate-800 bg-slate-900 p-4"
        >
          <div className="flex items-center gap-2 mb-3">
            {snapshot.quorum_met
              ? <CheckCircle className="w-4 h-4 text-green-400" />
              : <AlertCircle className="w-4 h-4 text-yellow-400" />
            }
            <span className="text-sm font-medium">
              Consensus {snapshot.quorum_met ? "Reached" : "Pending"}
            </span>
            <span className="text-xs text-slate-500 ml-auto">
              {snapshot.total_voters} voters · Quorum: {(snapshot.quorum_threshold * 100).toFixed(0)}%
            </span>
          </div>

          <div className="grid grid-cols-3 gap-3">
            {(["FOR", "AGAINST", "ABSTAIN"] as const).map((choice) => {
              const count = snapshot.vote_tally[choice] ?? 0;
              const weight = snapshot.weighted_tally[choice] ?? 0;
              const total = Object.values(snapshot.vote_tally).reduce((s, v) => s + (v as number), 0);
              const pct = total > 0 ? (count / total) * 100 : 0;
              const meta = choice === "FOR" ? POSITION_META.FOR : choice === "AGAINST" ? POSITION_META.AGAINST : POSITION_META.NEUTRAL;
              return (
                <div key={choice} className="text-center">
                  <div className="text-2xl font-bold" style={{ color: meta.color }}>{count}</div>
                  <div className="text-[10px] text-slate-500">{choice} ({pct.toFixed(0)}%)</div>
                  <div className="h-1.5 rounded-full bg-slate-800 mt-1 overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${pct}%` }}
                      transition={{ duration: 0.5 }}
                      className="h-full rounded-full"
                      style={{ backgroundColor: meta.color }}
                    />
                  </div>
                  <div className="text-[10px] text-slate-600 mt-0.5">w: {weight.toFixed(1)}</div>
                </div>
              );
            })}
          </div>
        </motion.div>
      )}
    </div>
  );
}
