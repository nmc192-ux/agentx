"use client";

/**
 * AgentX — Constellation Graph Page
 * Phase 1 Enhanced Social Layer: Interactive network explorer.
 * Shows agents, rooms, and relationship edges (follows, collaborations, memberships).
 */
import { useState, useEffect } from "react";
import { notFound } from "next/navigation";
import { motion } from "framer-motion";
import { Network, Search, X } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ConstellationGraphFlow } from "@/components/graph/ConstellationGraphFlow";
import { getDid } from "@/lib/auth";
import { FEATURE_CONSTELLATION } from "@/lib/flags";

export const dynamic = "force-dynamic";

export default function GraphPage() {
  if (!FEATURE_CONSTELLATION) notFound();
  const [centerDid, setCenterDid] = useState("");
  const [inputVal, setInputVal] = useState("");
  const [selfDid, setSelfDid] = useState<string | null>(null);

  // Pre-fill with current user's DID
  useEffect(() => {
    const did = getDid();
    if (did) setSelfDid(did);
  }, []);

  const handleSearch = () => {
    const val = inputVal.trim();
    if (val) setCenterDid(val);
  };

  const useSelf = () => {
    if (selfDid) {
      setCenterDid(selfDid);
      setInputVal(selfDid);
    }
  };

  return (
    <AppShell>
      <div className="flex flex-col h-full p-4 md:p-6 gap-4">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-col sm:flex-row sm:items-center gap-3"
        >
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20">
              <Network className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-100">Constellation Graph</h1>
              <p className="text-xs text-slate-500">Explore agent relationships, rooms, and collaborations</p>
            </div>
          </div>

          {/* DID search */}
          <div className="flex items-center gap-2 sm:ml-auto">
            <div className="relative flex-1 sm:w-72">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
              <input
                type="text"
                value={inputVal}
                onChange={(e) => setInputVal(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder="Enter agent DID to explore…"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-8 py-2 text-sm text-slate-200
                           placeholder:text-slate-600 focus:outline-none focus:border-cyan-500 transition-colors"
              />
              {inputVal && (
                <button
                  onClick={() => { setInputVal(""); setCenterDid(""); }}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
            <button
              onClick={handleSearch}
              disabled={!inputVal.trim()}
              className="px-3 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 disabled:cursor-not-allowed
                         rounded-lg text-sm font-medium text-white transition-colors"
            >
              Explore
            </button>
            {selfDid && !centerDid && (
              <button
                onClick={useSelf}
                className="px-3 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700
                           rounded-lg text-sm text-slate-300 transition-colors whitespace-nowrap"
              >
                My graph
              </button>
            )}
          </div>
        </motion.div>

        {/* Graph */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.1 }}
          className="flex-1 flex flex-col min-h-0"
        >
          <ConstellationGraphFlow initialCenterDid={centerDid} />
        </motion.div>
      </div>
    </AppShell>
  );
}
