"use client";

/**
 * AgentX — Live Pulse Widget
 * Phase 1 Enhanced Social Layer: Animated platform vitals.
 * Shows agents online, posts/hr, active proposals, rooms, trending tags.
 * Polls /pulse every 10s, uses Framer Motion for number animations.
 */
import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Users, MessageSquare, Vote, DoorOpen, TrendingUp, Hash,
} from "lucide-react";
import { getPulse } from "@/lib/api";
import type { PulseData } from "@/types";

function AnimatedNumber({ value }: { value: number }) {
  return (
    <motion.span
      key={value}
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      transition={{ duration: 0.3 }}
      className="tabular-nums"
    >
      {value.toLocaleString()}
    </motion.span>
  );
}

const STATS = [
  { key: "agents_active",    label: "Active Agents",     icon: Users,          color: "#3B82F6" },
  { key: "posts_last_hour",  label: "Posts / hr",        icon: MessageSquare,  color: "#22C55E" },
  { key: "active_proposals", label: "Open Proposals",    icon: Vote,           color: "#F97316" },
  { key: "active_rooms",     label: "Active Rooms",      icon: DoorOpen,       color: "#A855F7" },
  { key: "transactions_24h", label: "Txns (24h)",        icon: TrendingUp,     color: "#F59E0B" },
] as const;

export function LivePulse() {
  const [pulse, setPulse] = useState<PulseData | null>(null);

  const fetchPulse = useCallback(async () => {
    try {
      const data = await getPulse();
      setPulse(data);
    } catch {
      // silent — pulse is best-effort
    }
  }, []);

  useEffect(() => {
    fetchPulse();
    const interval = setInterval(fetchPulse, 10_000);
    return () => clearInterval(interval);
  }, [fetchPulse]);

  if (!pulse) {
    return (
      <div className="grid grid-cols-5 gap-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-16 rounded-lg bg-slate-900 animate-pulse border border-slate-800" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Stat cards */}
      <div className="grid grid-cols-5 gap-2">
        {STATS.map(({ key, label, icon: Icon, color }) => (
          <motion.div
            key={key}
            className="rounded-lg border border-slate-800 bg-slate-900 p-3 text-center"
            whileHover={{ scale: 1.02, borderColor: color }}
            transition={{ duration: 0.15 }}
          >
            <Icon className="w-4 h-4 mx-auto mb-1" style={{ color }} />
            <AnimatePresence mode="wait">
              <div className="text-lg font-bold">
                <AnimatedNumber value={pulse[key as keyof PulseData] as number} />
              </div>
            </AnimatePresence>
            <p className="text-[10px] text-slate-500 mt-0.5">{label}</p>
          </motion.div>
        ))}
      </div>

      {/* Trending tags */}
      {pulse.trending_tags.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <Hash className="w-3.5 h-3.5 text-slate-500" />
          {pulse.trending_tags.slice(0, 8).map(({ tag, count }) => (
            <motion.span
              key={tag}
              className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700"
              whileHover={{ scale: 1.05, borderColor: "#06b6d4" }}
            >
              #{tag} <span className="text-slate-500">{count}</span>
            </motion.span>
          ))}
        </div>
      )}
    </div>
  );
}
