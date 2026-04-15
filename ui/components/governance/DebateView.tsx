"use client";

/**
 * AgentX — Debate View Component
 * Phase 1 Enhanced Social Layer: Structured debate rounds + statements + consensus.
 */
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  MessageSquare, ThumbsUp, ThumbsDown, Minus,
  ChevronRight,
} from "lucide-react";
import { getDebate } from "@/lib/api";
import type { DebateDetail, DebatePhase, DebateStatement } from "@/types";
import { ConsensusMeter } from "./ConsensusMeter";

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

      {/* Consensus Meter with replay */}
      <ConsensusMeter proposalId={proposalId} latestSnapshot={snapshot} />
    </div>
  );
}
