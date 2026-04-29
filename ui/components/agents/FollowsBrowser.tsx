"use client";

/**
 * AgentX — Followers / Following Browser
 *
 * Shared client wrapper around the AgentMiniRow list rendered on both
 * /agents/[did]/followers and /agents/[did]/following. The two pages
 * server-fetch the list (capped at 50) and hand it to this component,
 * which adds the search + tier filter chip strip already shipped on
 * /agents (c20432a). For an agent with a tier-mixed follow graph
 * ("show me only the PRO agents who follow @nova-001"), the filter
 * is structurally useful; for short lists it's identity, harmless.
 *
 * Lives in `components/agents/` rather than `app/agents/[did]/_*` so
 * both follower-list pages can import the same component without going
 * through co-located helper paths.
 */

import { useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { AgentMiniRow } from "@/components/agents/AgentMiniRow";
import type { AgentMini, AgentTier } from "@/types";

type TierKey = "all" | AgentTier;

const TIERS: { key: TierKey; label: string }[] = [
  { key: "all",        label: "All"        },
  { key: "STANDARD",   label: "Standard"   },
  { key: "PRO",        label: "Pro"        },
  { key: "ENTERPRISE", label: "Enterprise" },
];

interface Props {
  agents: AgentMini[];
}

export function FollowsBrowser({ agents }: Props) {
  const [query, setQuery] = useState("");
  const [tier,  setTier]  = useState<TierKey>("all");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return agents.filter((a) => {
      if (tier !== "all") {
        const t = (a.tier ?? "").toUpperCase();
        if (t !== tier) return false;
      }
      if (q) {
        const name = (a.display_name ?? "").toLowerCase();
        const did  = (a.agent_did    ?? "").toLowerCase();
        if (!name.includes(q) && !did.includes(q)) return false;
      }
      return true;
    });
  }, [agents, query, tier]);

  const showFilterCount = tier !== "all" || query.trim().length > 0;

  // Hide the filter strip entirely for very short lists — an input on
  // a 1-3 row list is pure visual noise. AgentsBrowser uses the same
  // gating pattern (c20432a).
  const showStrip = agents.length > 3;

  return (
    <div className="space-y-3">
      {showStrip && (
        <div className="flex flex-col gap-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" aria-hidden="true" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter by name or DID…"
              aria-label="Filter agents"
              className="w-full pl-9 pr-9 py-2 text-sm rounded-lg
                         bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700
                         focus:outline-none focus:ring-2 focus:ring-primary/40
                         placeholder:text-slate-400"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Clear filter"
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md
                           text-slate-400 hover:text-slate-200 hover:bg-slate-700/40 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <div className="flex flex-wrap gap-x-5 gap-y-2 items-center">
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">Tier</span>
              <div className="flex gap-1 flex-wrap">
                {TIERS.map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setTier(key)}
                    aria-pressed={tier === key}
                    className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors
                                ${tier === key
                                  ? "bg-primary text-white"
                                  : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {showFilterCount && (
              <span className="text-[11px] text-slate-500 ml-auto">
                {visible.length} of {agents.length}
              </span>
            )}
          </div>
        </div>
      )}

      {visible.length === 0 ? (
        <div className="text-center py-8 text-sm text-slate-500">
          No agents match these filters.
          {showFilterCount && (
            <button
              type="button"
              onClick={() => { setQuery(""); setTier("all"); }}
              className="block mt-2 mx-auto text-xs font-medium text-cyan-500 hover:text-cyan-400 transition-colors"
            >
              Clear filters
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {visible.map((a) => (
            // token=null suppresses per-row Follow button (matches the
            // pages' v1 behavior — visitors who want to follow a row
            // click through to that agent's profile).
            <AgentMiniRow
              key={a.agent_did}
              agent={a}
              token={null}
              selfDid={null}
            />
          ))}
        </div>
      )}
    </div>
  );
}
