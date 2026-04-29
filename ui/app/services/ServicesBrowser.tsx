"use client";

/**
 * AgentX — Services directory client browser
 *
 * Third sibling to AgentsBrowser (c20432a) + CapabilitiesBrowser
 * (425b63f). The /services page server-renders the active-services
 * list; this component layers on the four filters every directory of
 * non-trivial size needs:
 *
 *   • Search — substring match on service_name + description.
 *     Existing groups-by-type rendering didn't help users with a
 *     specific intent ("I need OCR"); discovery requires text search.
 *   • Service-type chips — auto-derived from the dataset (top N types
 *     by count). Service types are dynamic strings (not a fixed enum
 *     like AgentTier or CapabilityLevel), so we read them off the
 *     prefetched list rather than hardcoding.
 *   • Sort — Name (alphabetical), Price (low→high, free first),
 *     Recent (created_at desc). Price-asc is the most common
 *     marketplace browse axis ("show me the cheapest" — same default
 *     Etsy / Stripe Atlas / Fiverr expose).
 *   • Active-only toggle — defaults on (browsing want-to-buy users
 *     don't want to see tombstoned listings) but flippable for the
 *     "what was this network capable of?" historical view.
 *
 * Drops the per-type section grouping the previous server render had —
 * grouping reads well at zero filter, but as soon as filter narrows,
 * each group collapses to 1-2 cards and the section headings become
 * empty noise. A single flat grid with the type chip strip is more
 * scalable. The chip set conveys the same "these are the categories
 * available" affordance.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { Search, X } from "lucide-react";
import type { Service } from "@/types";

type SortKey = "name" | "price" | "recent";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "name",   label: "Name"  },
  { key: "price",  label: "Price" },
  { key: "recent", label: "Recent"},
];

const MAX_TYPE_CHIPS = 6;

interface Props {
  services: Service[];
}

function priceForSort(s: Service): number {
  // Free always sorts first; missing-price sorts last (it's not really
  // priced so it shouldn't compete with priced offerings on a "Price"
  // ascending sort). Backend doesn't promise a numeric price for
  // pricing_model="free", so we coerce explicitly.
  if (s.pricing_model === "free" || s.price === 0) return 0;
  if (typeof s.price === "number") return s.price;
  return Number.POSITIVE_INFINITY;
}

function formatPrice(s: Service): string | null {
  if (s.price == null && !s.pricing_model) return null;
  if (s.pricing_model === "free" || s.price === 0) return "Free";
  if (s.price == null) return s.pricing_model ?? null;
  const priceStr = s.price.toFixed(2).replace(/\.00$/, "");
  return s.pricing_model ? `$${priceStr} ${s.pricing_model}` : `$${priceStr}`;
}

export function ServicesBrowser({ services }: Props) {
  const [query,      setQuery]      = useState("");
  const [type,       setType]       = useState<"all" | string>("all");
  const [sort,       setSort]       = useState<SortKey>("name");
  const [activeOnly, setActiveOnly] = useState(true);

  // Auto-derive type chip set from the dataset. Sort by count desc so
  // the most populated categories surface; cap at MAX_TYPE_CHIPS to
  // keep the row from wrapping wildly on a network with many service
  // types. Less-used types remain reachable via the Search input.
  const typeChips = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of services) {
      if (!s.service_type) continue;
      counts.set(s.service_type, (counts.get(s.service_type) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, MAX_TYPE_CHIPS)
      .map(([t]) => t);
  }, [services]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();

    const filtered = services.filter((s) => {
      if (activeOnly && !s.is_active) return false;
      if (type !== "all" && s.service_type !== type) return false;
      if (q) {
        const inName = s.service_name?.toLowerCase().includes(q);
        const inDesc = s.description?.toLowerCase().includes(q);
        if (!inName && !inDesc) return false;
      }
      return true;
    });

    const sorted = filtered.slice();
    if (sort === "name") {
      sorted.sort((a, b) => a.service_name.localeCompare(b.service_name));
    } else if (sort === "price") {
      sorted.sort((a, b) => priceForSort(a) - priceForSort(b));
    } else {
      // recent — newest created_at first, fall back to service_id for stable
      // ordering on identical timestamps (e.g. seed batches).
      sorted.sort((a, b) => {
        const ta = Date.parse(a.created_at) || 0;
        const tb = Date.parse(b.created_at) || 0;
        if (tb !== ta) return tb - ta;
        return a.service_id.localeCompare(b.service_id);
      });
    }
    return sorted;
  }, [services, query, type, sort, activeOnly]);

  const showFilterCount =
    type !== "all" || query.trim().length > 0 || !activeOnly;

  return (
    <div>
      {/* Controls row — same visual language as /agents and /capabilities */}
      <div className="flex flex-col gap-3 mb-5">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" aria-hidden="true" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search services by name or description…"
            aria-label="Search services"
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

          {/* Type chips — only render if there are actual types in the
              dataset (an empty-network deploy shouldn't show a stub). */}
          {typeChips.length > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">Type</span>
              <div className="flex gap-1 flex-wrap">
                <button
                  type="button"
                  onClick={() => setType("all")}
                  aria-pressed={type === "all"}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors
                              ${type === "all"
                                ? "bg-primary text-white"
                                : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"}`}
                >
                  All
                </button>
                {typeChips.map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setType(t)}
                    aria-pressed={type === t}
                    title={t}
                    className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors capitalize
                                ${type === t
                                  ? "bg-primary text-white"
                                  : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"}`}
                  >
                    {t.replace(/[-_]/g, " ")}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Active-only toggle — defaults on (most users want what's
              bookable now). Click to flip and surface tombstones. */}
          <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-500 cursor-pointer">
            <input
              type="checkbox"
              checked={activeOnly}
              onChange={(e) => setActiveOnly(e.target.checked)}
              className="w-3.5 h-3.5 rounded text-primary
                         focus:ring-primary/40 focus:ring-offset-0"
            />
            Active only
          </label>

          {showFilterCount && (
            <span className="text-[11px] text-slate-500 ml-auto">
              {visible.length} of {services.length}
            </span>
          )}
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="text-center py-10 text-sm text-slate-500">
          No services match these filters.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {visible.map((s) => {
            const priceLabel = formatPrice(s);
            const isFree = s.pricing_model === "free" || s.price === 0;
            return (
              <Link
                key={s.service_id}
                href={`/agents/${encodeURIComponent(s.agent_did)}`}
                className={`block border rounded-xl p-4 transition-colors
                            flex flex-col gap-2
                            ${
                              s.is_active
                                ? "border-slate-200 dark:border-slate-800 hover:border-cyan-500/40 hover:shadow-sm"
                                : "border-slate-200 dark:border-slate-800 opacity-50 hover:opacity-80"
                            }
                            focus-visible:outline-none focus-visible:ring-2
                            focus-visible:ring-cyan-500/60`}
                title={`${s.service_name} by ${s.agent_did}${
                  priceLabel ? ` — ${priceLabel}` : ""
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-sm font-semibold truncate">
                    {s.service_name}
                  </h3>
                  {!s.is_active && (
                    <span
                      className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full
                                 border border-slate-500/40 text-slate-500 flex-shrink-0"
                      title="This service is currently inactive"
                    >
                      inactive
                    </span>
                  )}
                </div>
                {/* Service type chip — replaces the section heading
                    grouping that the prior server render used. */}
                {s.service_type && (
                  <span
                    className="self-start inline-flex items-center px-1.5 py-0.5 rounded
                               text-[10px] font-semibold uppercase tracking-wide
                               border border-slate-200 dark:border-slate-700
                               text-slate-500 bg-slate-50 dark:bg-slate-800/40
                               capitalize"
                  >
                    {s.service_type.replace(/[-_]/g, " ")}
                  </span>
                )}
                {s.description && (
                  <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
                    {s.description}
                  </p>
                )}
                <div className="flex items-center justify-between gap-2 mt-auto pt-1">
                  {priceLabel ? (
                    <span
                      className={`text-xs font-semibold ${
                        isFree
                          ? "text-emerald-500 dark:text-emerald-400"
                          : "text-slate-700 dark:text-slate-300"
                      }`}
                    >
                      {priceLabel}
                    </span>
                  ) : (
                    <span className="text-[11px] text-slate-400 italic">
                      no pricing
                    </span>
                  )}
                  {s.capabilities && s.capabilities.length > 0 && (
                    <span
                      className="text-[10px] text-slate-500 dark:text-slate-400"
                      title={`Backed by capabilities: ${s.capabilities.join(", ")}`}
                    >
                      {s.capabilities.length} capabilit
                      {s.capabilities.length === 1 ? "y" : "ies"}
                    </span>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
