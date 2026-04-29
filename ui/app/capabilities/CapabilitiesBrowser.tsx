"use client";

/**
 * AgentX — Capabilities directory client browser
 *
 * Sister to /agents/AgentsBrowser (c20432a). The /capabilities page
 * server-renders the grouped list and now hands it to this component,
 * which adds the two filters every directory of >20 items needs:
 *
 *   • Search input — substring match on capability name. The directory
 *     scales linearly with how many distinct capabilities the network
 *     declares; once it's past ~20 the unfiltered grid becomes a
 *     scroll-to-find experience that fights the discovery intent.
 *   • Level filter chips — All / Expert / Advanced / Intermediate /
 *     Basic. AgentX's level taxonomy is a structural discovery axis
 *     that was already encoded in the data (every group rolls up the
 *     per-level claim counts) but not exposed as a filter. "Show me
 *     only the expert-tier capabilities" is the natural follow-up to
 *     "what's the deepest skill on this network?".
 *
 * Filter is "any-match": a group passes the level filter if at least
 * one claim sits at that level. So "code-review" with mixed
 * basic/expert claims appears under both All and Expert; sorting is
 * preserved (adoption desc, then verifiedCount, then alphabetical).
 *
 * Backend pre-computes the rollup; this component never re-fetches —
 * filtering is pure client-side over the prefetched `groups` prop.
 * Cards link to `/capabilities/[representativeId]` exactly as before.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { Search, X } from "lucide-react";
import type { CapabilityLevel } from "@/types";

type LevelFilter = "all" | CapabilityLevel;

/**
 * Plain-data mirror of `CapabilityGroup` from `page.tsx`. The original
 * type uses `Set<string>` for `agents`, which can't cross the
 * server-client boundary (Sets aren't serialisable). The page caller
 * converts the rollup once before handing it here.
 */
export interface BrowserGroup {
  name:                string;
  agentCount:          number;
  totalEndorsements:   number;
  verifiedCount:       number;
  levels:              Partial<Record<CapabilityLevel, number>>;
  representativeId:    string;
  representativeLevel: CapabilityLevel;
}

const LEVEL_ORDER_DISPLAY: readonly CapabilityLevel[] = [
  "expert",
  "advanced",
  "intermediate",
  "basic",
];

const LEVEL_STYLE: Record<CapabilityLevel, string> = {
  expert:       "border-purple-500/40 text-purple-500 dark:text-purple-400",
  advanced:     "border-cyan-500/40 text-cyan-500 dark:text-cyan-400",
  intermediate: "border-blue-500/40 text-blue-500 dark:text-blue-400",
  basic:        "border-slate-500/40 text-slate-500 dark:text-slate-400",
};

const LEVEL_FILTERS: { key: LevelFilter; label: string }[] = [
  { key: "all",          label: "All"          },
  { key: "expert",       label: "Expert"       },
  { key: "advanced",     label: "Advanced"     },
  { key: "intermediate", label: "Intermediate" },
  { key: "basic",        label: "Basic"        },
];

interface Props {
  groups: BrowserGroup[];
}

export function CapabilitiesBrowser({ groups }: Props) {
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState<LevelFilter>("all");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return groups.filter((g) => {
      if (q && !g.name.toLowerCase().includes(q)) return false;
      // Any-match level filter — pass when at least one claim sits at
      // the picked level. A code-review group with mixed basic/expert
      // claims appears under both filters, which matches user intent
      // ("show me capabilities where someone is at expert level").
      if (level !== "all" && (g.levels[level] ?? 0) === 0) return false;
      return true;
    });
  }, [groups, query, level]);

  const showFilterCount = level !== "all" || query.trim().length > 0;

  return (
    <div>
      {/* Controls — same visual language as /agents AgentsBrowser
          (c20432a) so the directory pages feel coherent. Search
          full-width on mobile, level chips below on a wrap-friendly
          row so the strip never crowds out content. */}
      <div className="flex flex-col gap-3 mb-5">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" aria-hidden="true" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search capabilities by name…"
            aria-label="Search capabilities"
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
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] uppercase tracking-wide text-slate-500">Level</span>
            <div className="flex gap-1 flex-wrap">
              {LEVEL_FILTERS.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setLevel(key)}
                  aria-pressed={level === key}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors
                              ${level === key
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
              {visible.length} of {groups.length}
            </span>
          )}
        </div>
      </div>

      {/* Results grid — visually identical to the prior server-rendered
          grid; only the data source changed. */}
      {visible.length === 0 ? (
        <div className="text-center py-10 text-sm text-slate-500">
          No capabilities match these filters.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {visible.map((g) => (
            <Link
              key={g.name}
              href={`/capabilities/${encodeURIComponent(g.representativeId)}`}
              title={`See agents who claim ${g.name}`}
              className="border border-slate-200 dark:border-slate-800 rounded-xl p-4
                         hover:border-cyan-500/40 hover:shadow-sm
                         dark:hover:border-cyan-500/40
                         transition-colors flex flex-col gap-2
                         focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-cyan-500/60"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-semibold truncate" title={g.name}>
                  {g.name}
                </h3>
                {g.verifiedCount > 0 && (
                  <span
                    className="inline-flex items-center gap-0.5 text-[10px] font-semibold
                               text-emerald-600 dark:text-emerald-400 flex-shrink-0"
                    title={`${g.verifiedCount} verified ${g.verifiedCount === 1 ? "claim" : "claims"}`}
                  >
                    <span className="material-symbols-outlined text-sm leading-none">
                      verified
                    </span>
                    {g.verifiedCount}
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                <span className="text-slate-700 dark:text-slate-300 font-medium">
                  {g.agentCount}
                </span>{" "}
                agent{g.agentCount === 1 ? "" : "s"}
                {g.totalEndorsements > 0 && (
                  <>
                    {" · "}
                    <span className="text-slate-700 dark:text-slate-300 font-medium">
                      {g.totalEndorsements}
                    </span>{" "}
                    endorsement{g.totalEndorsements === 1 ? "" : "s"}
                  </>
                )}
              </p>
              <div className="flex flex-wrap gap-1 mt-auto">
                {LEVEL_ORDER_DISPLAY.map((lvl) => {
                  const n = g.levels[lvl] ?? 0;
                  if (!n) return null;
                  return (
                    <span
                      key={lvl}
                      className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full
                                  border ${LEVEL_STYLE[lvl]} bg-transparent`}
                      title={`${n} agent${n === 1 ? "" : "s"} at ${lvl} level`}
                    >
                      {lvl}
                      <span className="ml-1 opacity-70">{n}</span>
                    </span>
                  );
                })}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
