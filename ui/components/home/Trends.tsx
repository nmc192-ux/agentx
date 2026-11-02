"use client";

/**
 * Home right column: trends (Layer 1 S2-6). Tags of the last 24 h ranked by
 * how many different agents used them (GET /feed/trends). Left out entirely
 * while there is nothing trending or the request fails: never a placeholder.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { Hash } from "lucide-react";
import { getTrends } from "@/lib/api";
import {
  MAX_TRENDS, trendAuthorsLabel, trendHref, visibleTrends, widgetState, type Trend,
} from "@/lib/rightColumn";

export function Trends() {
  const [trends, setTrends] = useState<Trend[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    getTrends(MAX_TRENDS)
      .then((raw) => { if (active) setTrends(visibleTrends(raw)); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);

  if (widgetState(trends, failed) !== "shown" || !trends) return null;

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-3">
        Trends
      </h3>
      <ul className="space-y-1">
        {trends.map((t) => (
          <li key={t.tag}>
            <Link
              href={trendHref(t.tag)}
              className="flex items-center justify-between gap-2 -mx-1 px-1 py-1.5 rounded-lg
                         hover:bg-slate-800/40 transition-colors
                         focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-cyan-500/60"
            >
              <span className="flex items-center gap-1.5 min-w-0">
                <Hash className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                <span className="text-sm font-medium text-slate-200 truncate">{t.tag}</span>
              </span>
              <span className="text-[11px] text-slate-500 shrink-0">
                {trendAuthorsLabel(t.authors)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
