"use client";

/**
 * AgentX — ConsensusMeter Component
 * Phase 1 Enhanced Social Layer: Animated consensus gauge with replay scrubber.
 *
 * Displays a semicircular gauge showing FOR vs AGAINST balance,
 * plus a timeline slider to scrub through historical snapshots.
 */
import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Play, Pause, SkipBack, SkipForward, Clock,
  CheckCircle, AlertCircle, Users,
} from "lucide-react";
import { getConsensusHistory } from "@/lib/api";
import type { ConsensusSnapshot } from "@/types";

// ── Gauge SVG constants ──────────────────────────────────────────────────────
const GAUGE_SIZE = 200;
const GAUGE_CX = GAUGE_SIZE / 2;
const GAUGE_CY = GAUGE_SIZE / 2 + 10;
const GAUGE_R = 75;
const STROKE_W = 14;
// Semicircle from π to 0 (left to right across top)
const ARC_START = Math.PI;
const ARC_LENGTH = Math.PI;

function polarToCart(cx: number, cy: number, r: number, angle: number) {
  return { x: cx + r * Math.cos(angle), y: cy - r * Math.sin(angle) };
}

function describeArc(cx: number, cy: number, r: number, startAngle: number, endAngle: number): string {
  const start = polarToCart(cx, cy, r, startAngle);
  const end = polarToCart(cx, cy, r, endAngle);
  const sweep = endAngle - startAngle <= Math.PI ? 0 : 1;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${sweep} 0 ${end.x} ${end.y}`;
}

// ── Needle component ─────────────────────────────────────────────────────────
function Needle({ angle, color }: { angle: number; color: string }) {
  const tip = polarToCart(GAUGE_CX, GAUGE_CY, GAUGE_R - STROKE_W / 2 - 4, angle);
  return (
    <motion.line
      x1={GAUGE_CX} y1={GAUGE_CY}
      x2={tip.x} y2={tip.y}
      stroke={color}
      strokeWidth={2.5}
      strokeLinecap="round"
      initial={false}
      animate={{ x2: tip.x, y2: tip.y }}
      transition={{ type: "spring", stiffness: 80, damping: 15 }}
    />
  );
}

// ── Main component ───────────────────────────────────────────────────────────
interface ConsensusMeterProps {
  proposalId: string;
  latestSnapshot?: ConsensusSnapshot | null;
}

export function ConsensusMeter({ proposalId, latestSnapshot }: ConsensusMeterProps) {
  const [timeline, setTimeline] = useState<ConsensusSnapshot[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(true);
  const playRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch history
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const history = await getConsensusHistory(proposalId);
        if (cancelled) return;
        if (history.length > 0) {
          setTimeline(history);
          setActiveIdx(history.length - 1);
        } else if (latestSnapshot) {
          setTimeline([latestSnapshot]);
          setActiveIdx(0);
        }
      } catch {
        if (latestSnapshot) {
          setTimeline([latestSnapshot]);
          setActiveIdx(0);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [proposalId, latestSnapshot]);

  const snap = timeline[activeIdx] ?? null;

  // Derived gauge values
  const { forPct, againstPct, abstainPct, needleAngle, needleColor, totalVotes } = useMemo(() => {
    if (!snap) return { forPct: 0, againstPct: 0, abstainPct: 0, needleAngle: ARC_START + ARC_LENGTH / 2, needleColor: "#6B7280", totalVotes: 0 };
    const f = snap.vote_tally["FOR"] ?? 0;
    const a = snap.vote_tally["AGAINST"] ?? 0;
    const ab = snap.vote_tally["ABSTAIN"] ?? 0;
    const total = f + a + ab;
    if (total === 0) return { forPct: 0, againstPct: 0, abstainPct: 0, needleAngle: ARC_START + ARC_LENGTH / 2, needleColor: "#6B7280", totalVotes: 0 };
    const fp = f / total;
    const ap = a / total;
    const abp = ab / total;
    // Needle: 0 = full AGAINST (left), 0.5 = neutral (top), 1 = full FOR (right)
    const ratio = total > 0 ? f / (f + a || 1) : 0.5;
    const angle = ARC_START + ratio * ARC_LENGTH;
    const color = ratio > 0.6 ? "#22C55E" : ratio < 0.4 ? "#EF4444" : "#F59E0B";
    return { forPct: fp * 100, againstPct: ap * 100, abstainPct: abp * 100, needleAngle: angle, needleColor: color, totalVotes: total };
  }, [snap]);

  // Playback controls
  const stopPlayback = useCallback(() => {
    if (playRef.current) clearInterval(playRef.current);
    playRef.current = null;
    setPlaying(false);
  }, []);

  const startPlayback = useCallback(() => {
    if (timeline.length <= 1) return;
    setPlaying(true);
    setActiveIdx(0);
    playRef.current = setInterval(() => {
      setActiveIdx((prev) => {
        if (prev >= timeline.length - 1) {
          stopPlayback();
          return timeline.length - 1;
        }
        return prev + 1;
      });
    }, 1200);
  }, [timeline.length, stopPlayback]);

  useEffect(() => () => { if (playRef.current) clearInterval(playRef.current); }, []);

  if (loading) {
    return <div className="h-64 rounded-xl bg-slate-900 animate-pulse border border-slate-800" />;
  }

  if (!snap) {
    return (
      <div className="text-center py-8 text-slate-500 border border-slate-800 rounded-xl">
        <AlertCircle className="w-5 h-5 mx-auto mb-2 opacity-30" />
        <p className="text-sm">No consensus data yet.</p>
      </div>
    );
  }

  // Arc paths for colored segments
  const forArcEnd = ARC_START + (forPct / 100) * ARC_LENGTH;
  const againstArcEnd = forArcEnd + (againstPct / 100) * ARC_LENGTH;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-slate-800 bg-slate-900 p-4"
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        {snap.quorum_met
          ? <CheckCircle className="w-4 h-4 text-green-400" />
          : <AlertCircle className="w-4 h-4 text-yellow-400" />
        }
        <span className="text-sm font-semibold text-slate-200">Consensus Meter</span>
        <span className="text-xs text-slate-500 ml-auto flex items-center gap-1">
          <Users className="w-3 h-3" />
          {snap.total_voters} voters
        </span>
      </div>

      {/* Gauge */}
      <div className="flex justify-center">
        <svg width={GAUGE_SIZE} height={GAUGE_SIZE / 2 + 30} viewBox={`0 0 ${GAUGE_SIZE} ${GAUGE_SIZE / 2 + 30}`}>
          {/* Background arc */}
          <path
            d={describeArc(GAUGE_CX, GAUGE_CY, GAUGE_R, ARC_START, ARC_START + ARC_LENGTH)}
            fill="none" stroke="#1E293B" strokeWidth={STROKE_W} strokeLinecap="round"
          />
          {/* FOR arc (green, from left) */}
          {forPct > 0 && (
            <motion.path
              d={describeArc(GAUGE_CX, GAUGE_CY, GAUGE_R, ARC_START, forArcEnd)}
              fill="none" stroke="#22C55E" strokeWidth={STROKE_W} strokeLinecap="round"
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }}
              transition={{ duration: 0.6 }}
            />
          )}
          {/* AGAINST arc (red) */}
          {againstPct > 0 && (
            <motion.path
              d={describeArc(GAUGE_CX, GAUGE_CY, GAUGE_R, forArcEnd, againstArcEnd)}
              fill="none" stroke="#EF4444" strokeWidth={STROKE_W} strokeLinecap="round"
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }}
              transition={{ duration: 0.6, delay: 0.1 }}
            />
          )}
          {/* ABSTAIN arc (gray) */}
          {abstainPct > 0 && (
            <motion.path
              d={describeArc(GAUGE_CX, GAUGE_CY, GAUGE_R, againstArcEnd, ARC_START + ARC_LENGTH)}
              fill="none" stroke="#6B7280" strokeWidth={STROKE_W} strokeLinecap="round"
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }}
              transition={{ duration: 0.6, delay: 0.2 }}
            />
          )}
          {/* Needle */}
          <Needle angle={needleAngle} color={needleColor} />
          {/* Center dot */}
          <circle cx={GAUGE_CX} cy={GAUGE_CY} r={4} fill={needleColor} />
          {/* Labels */}
          <text x={GAUGE_CX - GAUGE_R - 4} y={GAUGE_CY + 16} fill="#EF4444" fontSize="10" textAnchor="middle">Against</text>
          <text x={GAUGE_CX + GAUGE_R + 4} y={GAUGE_CY + 16} fill="#22C55E" fontSize="10" textAnchor="middle">For</text>
        </svg>
      </div>

      {/* Vote breakdown row */}
      <div className="grid grid-cols-3 gap-2 text-center mt-1 mb-3">
        {([
          { key: "FOR", color: "#22C55E", pct: forPct },
          { key: "AGAINST", color: "#EF4444", pct: againstPct },
          { key: "ABSTAIN", color: "#6B7280", pct: abstainPct },
        ] as const).map(({ key, color, pct }) => (
          <div key={key}>
            <div className="text-lg font-bold" style={{ color }}>{snap.vote_tally[key] ?? 0}</div>
            <div className="text-[10px] text-slate-500">{key} ({pct.toFixed(0)}%)</div>
          </div>
        ))}
      </div>

      {/* Quorum bar */}
      <div className="mb-3">
        <div className="flex items-center justify-between text-[10px] text-slate-500 mb-1">
          <span>Quorum Progress</span>
          <span>{snap.quorum_met ? "Reached" : `${(snap.quorum_threshold * 100).toFixed(0)}% required`}</span>
        </div>
        <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
          <motion.div
            className="h-full rounded-full"
            style={{ backgroundColor: snap.quorum_met ? "#22C55E" : "#F59E0B" }}
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(100, snap.quorum_met ? 100 : (snap.total_voters / Math.max(1, snap.total_voters / snap.quorum_threshold)) * 100)}%` }}
            transition={{ duration: 0.5 }}
          />
        </div>
      </div>

      {/* Replay scrubber */}
      {timeline.length > 1 && (
        <div className="border-t border-slate-800 pt-3">
          <div className="flex items-center gap-2 mb-2">
            <Clock className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-xs font-medium text-slate-400">Replay Timeline</span>
            <span className="text-[10px] text-slate-600 ml-auto">
              {activeIdx + 1} / {timeline.length} snapshots
            </span>
          </div>

          {/* Transport controls */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => { stopPlayback(); setActiveIdx(0); }}
              className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
              title="First snapshot"
            >
              <SkipBack className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={playing ? stopPlayback : startPlayback}
              className="p-1.5 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors"
              title={playing ? "Pause" : "Play"}
            >
              {playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
            </button>
            <button
              onClick={() => { stopPlayback(); setActiveIdx(timeline.length - 1); }}
              className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
              title="Latest snapshot"
            >
              <SkipForward className="w-3.5 h-3.5" />
            </button>

            {/* Slider */}
            <input
              type="range"
              min={0}
              max={timeline.length - 1}
              value={activeIdx}
              onChange={(e) => { stopPlayback(); setActiveIdx(Number(e.target.value)); }}
              className="flex-1 h-1 appearance-none bg-slate-700 rounded-full cursor-pointer
                         [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3
                         [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full
                         [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:cursor-pointer"
            />
          </div>

          {/* Timestamp */}
          <AnimatePresence mode="wait">
            <motion.div
              key={snap.snapshot_id}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-[10px] text-slate-600 text-center mt-1"
            >
              {new Date(snap.created_at).toLocaleString()}
            </motion.div>
          </AnimatePresence>
        </div>
      )}

      {/* Weighted tally (if ERC-8004) */}
      {snap.weighted_tally && Object.values(snap.weighted_tally).some((v) => v !== snap.vote_tally[Object.keys(snap.weighted_tally)[Object.values(snap.weighted_tally).indexOf(v)]]) && (
        <div className="border-t border-slate-800 pt-2 mt-2">
          <div className="text-[10px] text-slate-500 mb-1">Weighted Tally (ERC-8004)</div>
          <div className="grid grid-cols-3 gap-2 text-center">
            {(["FOR", "AGAINST", "ABSTAIN"] as const).map((k) => (
              <div key={k} className="text-xs text-slate-400">
                {(snap.weighted_tally[k] ?? 0).toFixed(1)}
              </div>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  );
}
