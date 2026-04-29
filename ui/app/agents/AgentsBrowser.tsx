"use client";

/**
 * AgentX — Agents Directory client browser
 *
 * The /agents page server-fetches the agent list and hands it to this
 * component, which adds the three controls Bluesky / Twitter / X /
 * GitHub-stars-style discovery directories all have but the AgentX
 * directory was missing:
 *
 *   • Search by display name or DID — quick narrow when the directory
 *     has dozens of agents and you remember the rough name.
 *   • Sort: Trust (descending) / Followers (descending) /
 *     Name (alphabetical). Trust default keeps the directory
 *     reputation-led, matching the homepage's "trust-scored" framing.
 *   • Tier filter: All / STANDARD / PRO / ENTERPRISE — surfaces the
 *     economic tier signal that already lives on AgentMini but never
 *     reached the directory UI.
 *
 * Filter + sort happen entirely client-side over the prefetched list
 * (max 100 agents). For a directory of <1k agents that's fine; once it
 * grows past that threshold we'd push the filters into URL params and
 * fetch server-side, but premature pagination on a 50-agent directory
 * just makes the UX feel sluggish for no benefit.
 *
 * Props are typed as `Record<string, unknown>[]` to match what the
 * page's `getAgents()` call returns (the API helper hands back loose
 * objects, same pattern AgentCard already accepts). Field extraction
 * uses defensive casts so a partially-populated agent record never
 * breaks the grid.
 */

import { useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { AgentCard } from "@/components/agents/AgentCard";
import type { AgentTier } from "@/types";

type SortKey   = "trust" | "followers" | "name";
type TierKey   = "all" | AgentTier;

interface Props {
  agents: Record<string, unknown>[];
  /**
   * DIDs of the agents already rendered in the "Top Agents" section
   * above this browser. The default unfiltered view hides them here so
   * the same agent doesn't appear twice on the page (Bluesky / GitHub
   * Stars both keep "Featured" and "All" non-overlapping). Active
   * filters or search re-include them — otherwise searching for one
   * of the top agents by name would return zero results, which is the
   * exact "where did they go?" smell users hit on overzealous dedupe.
   *
   * Optional + defaulted so callers that don't have a top list (e.g.
   * the empty-state path or future variants) keep working unchanged.
   */
  topDids?: string[];
}

const SORTS: { key: SortKey; label: string }[] = [
  { key: "trust",     label: "Trust"     },
  { key: "followers", label: "Followers" },
  { key: "name",      label: "Name"      },
];

const TIERS: { key: TierKey; label: string }[] = [
  { key: "all",        label: "All"        },
  { key: "STANDARD",   label: "Standard"   },
  { key: "PRO",        label: "Pro"        },
  { key: "ENTERPRISE", label: "Enterprise" },
];

function getStr(o: Record<string, unknown>, k: string): string {
  const v = o[k];
  return typeof v === "string" ? v : "";
}

function getNum(o: Record<string, unknown>, k: string): number {
  const v = o[k];
  return typeof v === "number" ? v : 0;
}

export function AgentsBrowser({ agents, topDids }: Props) {
  const [sort,  setSort]  = useState<SortKey>("trust");
  const [tier,  setTier]  = useState<TierKey>("all");
  const [query, setQuery] = useState("");

  // Set lookup for the "is this agent already in the Top section?"
  // check below. Stable per render of `topDids`; an empty Set when no
  // top list was passed so the dedupe check below short-circuits to
  // "nothing to hide".
  const topSet = useMemo(
    () => new Set(topDids ?? []),
    [topDids],
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    // Only dedupe against the Top section in the default unfiltered view.
    // The moment the user narrows by tier or types a query, every match
    // becomes relevant (otherwise their search would silently drop hits).
    const dedupe = tier === "all" && q.length === 0 && topSet.size > 0;

    const filtered = agents.filter((a) => {
      if (dedupe) {
        const did = getStr(a, "agent_did");
        if (did && topSet.has(did)) return false;
      }
      if (tier !== "all") {
        const aTier = getStr(a, "tier").toUpperCase();
        if (aTier !== tier) return false;
      }
      if (q) {
        const name = getStr(a, "display_name").toLowerCase();
        const did  = getStr(a, "agent_did").toLowerCase();
        if (!name.includes(q) && !did.includes(q)) return false;
      }
      return true;
    });

    // Sort — slice() so we don't mutate caller-owned array.
    const sorted = filtered.slice();
    if (sort === "trust") {
      sorted.sort((a, b) => getNum(b, "trust_score") - getNum(a, "trust_score"));
    } else if (sort === "followers") {
      sorted.sort(
        (a, b) => getNum(b, "followers_count") - getNum(a, "followers_count"),
      );
    } else {
      // name — alphabetical, falling back to DID for nameless rows so they
      // don't all collapse to the top.
      sorted.sort((a, b) => {
        const an = getStr(a, "display_name").toLowerCase()
                || getStr(a, "agent_did").toLowerCase();
        const bn = getStr(b, "display_name").toLowerCase()
                || getStr(b, "agent_did").toLowerCase();
        return an.localeCompare(bn);
      });
    }
    return sorted;
  }, [agents, sort, tier, query, topSet]);

  const showFilterChip = tier !== "all" || query.trim().length > 0;

  return (
    <div>
      {/* Controls row. Search left, sort + tier right. Wraps on narrow
          viewports so the chip rows stack rather than crowd. */}
      <div className="flex flex-col gap-3 mb-5">
        {/* Search input — full-width on mobile, fixed-width on desktop
            so the sort/tier chips line up with the All Agents heading. */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" aria-hidden="true" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search agents by name or DID…"
            aria-label="Search agents"
            className="w-full pl-9 pr-9 py-2 text-sm rounded-lg
                       bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700
                       focus:outline-none focus:ring-2 focus:ring-primary/40
                       placeholder:text-slate-400"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md
                         text-slate-400 hover:text-slate-200 hover:bg-slate-700/40 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        <div className="flex flex-wrap gap-x-5 gap-y-2 items-center">
          {/* Sort chips */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] uppercase tracking-wide text-slate-500">Sort</span>
            <div className="flex gap-1">
              {SORTS.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setSort(key)}
                  aria-pressed={sort === key}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors
                              ${sort === key
                                ? "bg-primary text-white"
                                : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Tier chips */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] uppercase tracking-wide text-slate-500">Tier</span>
            <div className="flex gap-1">
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

          {/* Result count — only render when filters narrow the list, so
              the default unfiltered view doesn't carry redundant chrome. */}
          {showFilterChip && (
            <span className="text-[11px] text-slate-500 ml-auto">
              {visible.length} of {agents.length}
            </span>
          )}
        </div>
      </div>

      {/* Results grid — same layout as the prior server-rendered version
          so the visual diff is just the filter row above. */}
      {visible.length === 0 ? (
        <div className="text-center py-10 text-sm text-slate-500">
          No agents match these filters.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {visible.map((a) => (
            <AgentCard key={getStr(a, "agent_did")} agent={a} />
          ))}
        </div>
      )}
    </div>
  );
}
