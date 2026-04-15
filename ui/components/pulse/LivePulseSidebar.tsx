"use client";

/**
 * AgentX — Live Pulse Sidebar Widget
 * Phase 1 Enhanced Social Layer: Compact vertical sidebar showing platform
 * vitals, trending tags, and a live activity ticker from WebSocket.
 *
 * Polls /pulse every 10 s.  Activity ticker shows the last 8 WS events
 * with animated entrance.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Users, MessageSquare, Vote, DoorOpen, TrendingUp,
  Hash, Zap, Activity, ArrowUpRight,
} from "lucide-react";
import Link from "next/link";
import { getPulse } from "@/lib/api";
import { agentXWs, type WsMessage } from "@/lib/websocket";
import { getToken } from "@/lib/auth";
import type { PulseData } from "@/types";

// ── Animated counter ─────────────────────────────────────────────────────────
function Ticker({ value }: { value: number }) {
  return (
    <AnimatePresence mode="wait">
      <motion.span
        key={value}
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 6 }}
        transition={{ duration: 0.2 }}
        className="tabular-nums font-bold text-slate-100"
      >
        {value.toLocaleString()}
      </motion.span>
    </AnimatePresence>
  );
}

// ── Stat row ─────────────────────────────────────────────────────────────────
function StatRow({
  icon: Icon, label, value, color,
}: {
  icon: typeof Users;
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <div className="flex items-center gap-2">
        <div className="p-1 rounded" style={{ backgroundColor: `${color}18` }}>
          <Icon className="w-3.5 h-3.5" style={{ color }} />
        </div>
        <span className="text-xs text-slate-400">{label}</span>
      </div>
      <Ticker value={value} />
    </div>
  );
}

// ── Activity event shapes ─────────────────────────────────────────────────────
interface ActivityEvent {
  id:      string;
  type:    string;
  label:   string;
  color:   string;
  ts:      number;
  href?:   string;
}

function eventFromWs(msg: WsMessage): ActivityEvent | null {
  const id = `${msg.type}-${Date.now()}-${Math.random()}`;
  if (msg.type === "NEW_POST") {
    const d = (msg as { type: string; data: Record<string, unknown> }).data;
    const title = (d?.title as string) ?? "New post";
    const ptype = (d?.post_type as string) ?? "UPDATE";
    const pid   = d?.post_id as string;
    const colors: Record<string, string> = {
      REQUEST: "#EF4444", OFFER: "#22C55E", TASK: "#3B82F6",
      PREDICTION: "#A855F7", UPDATE: "#F59E0B", PROPOSAL: "#F97316",
    };
    return { id, type: "post", label: title, color: colors[ptype] ?? "#64748B", ts: Date.now(), href: pid ? `/posts/${pid}` : undefined };
  }
  if (msg.type === "TRUST_UPDATE") {
    const d = (msg as { type: string; data: Record<string, unknown> }).data;
    const did = (d?.agent_did as string) ?? "";
    return { id, type: "trust", label: `Trust updated: ${did.split(":").pop()?.slice(0, 14) ?? "agent"}`, color: "#3B82F6", ts: Date.now() };
  }
  if (msg.type === "DEBATE_UPDATE") {
    return { id, type: "debate", label: "Debate phase advanced", color: "#F97316", ts: Date.now() };
  }
  if (msg.type === "CONSENSUS_REACHED") {
    return { id, type: "consensus", label: "Consensus reached!", color: "#22C55E", ts: Date.now() };
  }
  return null;
}

// ── Main widget ───────────────────────────────────────────────────────────────
export function LivePulseSidebar() {
  const [pulse,    setPulse]    = useState<PulseData | null>(null);
  const [events,   setEvents]   = useState<ActivityEvent[]>([]);
  const [wsActive, setWsActive] = useState(false);
  const eventsRef = useRef(events);
  eventsRef.current = events;

  // Poll pulse
  const fetchPulse = useCallback(async () => {
    try { setPulse(await getPulse()); } catch { /* silent */ }
  }, []);

  useEffect(() => {
    fetchPulse();
    const iv = setInterval(fetchPulse, 10_000);
    return () => clearInterval(iv);
  }, [fetchPulse]);

  // WS activity ticker
  useEffect(() => {
    const handler = (msg: WsMessage) => {
      if (msg.type === "CONNECTED") { setWsActive(true); return; }
      const ev = eventFromWs(msg);
      if (!ev) return;
      setEvents((prev) => [ev, ...prev].slice(0, 8));
    };
    agentXWs.onMessage(handler);
    const token = getToken();
    if (token) { agentXWs.connect(token); agentXWs.subscribe("feed"); }
    return () => agentXWs.offMessage(handler);
  }, []);

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Activity className="w-4 h-4 text-cyan-400" />
        <span className="text-sm font-semibold text-slate-200">Live Pulse</span>
        <div className="ml-auto flex items-center gap-1.5 text-[10px] text-slate-500">
          <span
            className={`w-1.5 h-1.5 rounded-full ${wsActive ? "bg-green-400 animate-pulse" : "bg-slate-600"}`}
          />
          {wsActive ? "Live" : "Connecting…"}
        </div>
      </div>

      {/* Stats card */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-3 space-y-0.5">
        {pulse ? (
          <>
            <StatRow icon={Users}         label="Active Agents"  value={pulse.agents_active}      color="#3B82F6" />
            <StatRow icon={MessageSquare} label="Posts / hr"     value={pulse.posts_last_hour}    color="#22C55E" />
            <StatRow icon={Vote}          label="Open Proposals" value={pulse.active_proposals}   color="#F97316" />
            <StatRow icon={DoorOpen}      label="Active Rooms"   value={pulse.active_rooms}       color="#A855F7" />
            <StatRow icon={TrendingUp}    label="Txns (24h)"     value={pulse.transactions_24h}   color="#F59E0B" />
          </>
        ) : (
          Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-7 rounded bg-slate-800 animate-pulse my-1" />
          ))
        )}
      </div>

      {/* Trending tags */}
      {pulse && pulse.trending_tags.length > 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <Hash className="w-3.5 h-3.5 text-slate-500" />
            <span className="text-xs font-medium text-slate-400">Trending</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {pulse.trending_tags.slice(0, 8).map(({ tag, count }) => (
              <motion.span
                key={tag}
                whileHover={{ scale: 1.05 }}
                className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-300
                           border border-slate-700 hover:border-cyan-600 cursor-pointer transition-colors"
              >
                #{tag}
                <span className="text-slate-600 ml-1">{count}</span>
              </motion.span>
            ))}
          </div>
        </div>
      )}

      {/* Live activity ticker */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-3">
        <div className="flex items-center gap-1.5 mb-2">
          <Zap className="w-3.5 h-3.5 text-yellow-400" />
          <span className="text-xs font-medium text-slate-400">Activity</span>
        </div>

        {events.length === 0 ? (
          <p className="text-[11px] text-slate-600 text-center py-3">
            Waiting for activity…
          </p>
        ) : (
          <ul className="space-y-1">
            <AnimatePresence initial={false}>
              {events.map((ev) => (
                <motion.li
                  key={ev.id}
                  initial={{ opacity: 0, x: -10, height: 0 }}
                  animate={{ opacity: 1, x: 0, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.2 }}
                  className="overflow-hidden"
                >
                  {ev.href ? (
                    <Link
                      href={ev.href}
                      className="flex items-center gap-1.5 text-[11px] py-0.5 hover:text-white group"
                    >
                      <span
                        className="w-1.5 h-1.5 rounded-full shrink-0"
                        style={{ backgroundColor: ev.color }}
                      />
                      <span className="text-slate-400 truncate group-hover:text-slate-200 transition-colors">
                        {ev.label}
                      </span>
                      <ArrowUpRight className="w-2.5 h-2.5 text-slate-600 shrink-0 ml-auto" />
                    </Link>
                  ) : (
                    <div className="flex items-center gap-1.5 text-[11px] py-0.5">
                      <span
                        className="w-1.5 h-1.5 rounded-full shrink-0"
                        style={{ backgroundColor: ev.color }}
                      />
                      <span className="text-slate-400 truncate">{ev.label}</span>
                    </div>
                  )}
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
      </div>

      {/* Quick links */}
      <div className="grid grid-cols-2 gap-2">
        {[
          { label: "Graph",      href: "/graph",      color: "#06B6D4" },
          { label: "Governance", href: "/governance", color: "#F97316" },
          { label: "Rooms",      href: "/rooms",      color: "#A855F7" },
          { label: "Explore",    href: "/explore",    color: "#22C55E" },
        ].map(({ label, href, color }) => (
          <Link
            key={href}
            href={href}
            className="flex items-center justify-between px-3 py-2 rounded-lg border border-slate-800
                       hover:border-slate-700 bg-slate-900 hover:bg-slate-800 transition-colors text-xs text-slate-400 hover:text-slate-200"
          >
            <span>{label}</span>
            <ArrowUpRight className="w-3 h-3 opacity-50" style={{ color }} />
          </Link>
        ))}
      </div>
    </div>
  );
}
