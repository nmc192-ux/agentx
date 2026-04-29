"use client";

/**
 * AgentX — Communities directory client browser
 *
 * Fourth sibling to AgentsBrowser (c20432a), CapabilitiesBrowser
 * (425b63f), and ServicesBrowser (9c6249c). The /communities page had
 * a search input visually wired into the layout — but the input had no
 * `onChange` handler attached, so typing did nothing. That made the
 * directory feel partially-implemented in a way the other directories
 * had already grown out of. This component finishes the job: real
 * search + sort over the prefetched list, matching the established
 * pattern across the site.
 *
 * Filter axes:
 *   • Search — substring on community name + description (description
 *     not always present, so the helper falls back to name-only when
 *     the field is missing).
 *   • Sort — Members (desc, the natural "biggest first" browse axis),
 *     Recent (created_at desc), Name (alphabetical). Members default
 *     since users browsing a directory typically want activity scale
 *     first.
 *
 * Defensive types: backend returns `Record<string, unknown>` rows
 * (same loose shape /agents and /capabilities use); the component
 * extracts fields through `getStr` / `getNum` rather than relying on a
 * typed Community interface (one doesn't exist yet, and adding one
 * would ripple into CommunityCard which uses the same loose shape).
 */

import { useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { CommunityCard } from "@/components/communities/CommunityCard";

type SortKey = "members" | "recent" | "name";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "members", label: "Members"},
  { key: "recent",  label: "Recent" },
  { key: "name",    label: "Name"   },
];

interface Props {
  communities: Record<string, unknown>[];
}

function getStr(o: Record<string, unknown>, k: string): string {
  const v = o[k];
  return typeof v === "string" ? v : "";
}
function getNum(o: Record<string, unknown>, k: string): number {
  const v = o[k];
  return typeof v === "number" ? v : 0;
}

export function CommunitiesBrowser({ communities }: Props) {
  const [query, setQuery] = useState("");
  const [sort,  setSort]  = useState<SortKey>("members");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();

    const filtered = communities.filter((c) => {
      if (!q) return true;
      const name = getStr(c, "name").toLowerCase();
      const desc = getStr(c, "description").toLowerCase();
      return name.includes(q) || desc.includes(q);
    });

    const sorted = filtered.slice();
    if (sort === "members") {
      sorted.sort((a, b) => getNum(b, "member_count") - getNum(a, "member_count"));
    } else if (sort === "recent") {
      // created_at is the canonical Date string on backend; fall back
      // to community_id alphabetical for stable ordering when timestamps
      // tie or are absent.
      sorted.sort((a, b) => {
        const ta = Date.parse(getStr(a, "created_at")) || 0;
        const tb = Date.parse(getStr(b, "created_at")) || 0;
        if (tb !== ta) return tb - ta;
        return getStr(a, "community_id").localeCompare(getStr(b, "community_id"));
      });
    } else {
      // name — alphabetical, case-insensitive
      sorted.sort((a, b) =>
        getStr(a, "name").toLowerCase().localeCompare(getStr(b, "name").toLowerCase()),
      );
    }
    return sorted;
  }, [communities, query, sort]);

  const showFilterCount = query.trim().length > 0;

  return (
    <div>
      {/* Controls — same visual language as /agents + /capabilities + /services */}
      <div className="flex flex-col gap-3 mb-5">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" aria-hidden="true" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search communities by name or description…"
            aria-label="Search communities"
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

          {showFilterCount && (
            <span className="text-[11px] text-slate-500 ml-auto">
              {visible.length} of {communities.length}
            </span>
          )}
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="text-center py-10 text-sm text-slate-500">
          No communities match this search.
        </div>
      ) : (
        // Same divider list the prior server render used — only the
        // input above is new. CommunityCard owns the per-row layout.
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800">
          {visible.map((c) => (
            <CommunityCard
              key={getStr(c, "community_id")}
              community={c}
            />
          ))}
        </div>
      )}
    </div>
  );
}
