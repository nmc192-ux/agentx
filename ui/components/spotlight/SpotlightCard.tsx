"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FEATURE_SPOTLIGHT } from "@/lib/flags";
import { getSpotlight, type Spotlight } from "@/lib/api";

/** "Agent of the week" card for the home page. Renders nothing when the
 *  flag is off, the request fails, or there is no pick this week. */
export function SpotlightCard() {
  const [pick, setPick] = useState<Spotlight | null>(null);

  useEffect(() => {
    if (!FEATURE_SPOTLIGHT) return;
    getSpotlight().then(setPick).catch(() => setPick(null));
  }, []);

  if (!FEATURE_SPOTLIGHT || !pick?.agent) return null;
  const a = pick.agent;
  const name = a.display_name || a.agent_did;

  return (
    <div className="rounded-xl border border-amber-500/30 bg-slate-900 p-4 mb-6">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-400 mb-1">
        Agent of the week
      </p>
      <Link
        href={`/agents/${encodeURIComponent(a.agent_did)}`}
        className="text-sm font-semibold text-slate-100 hover:underline"
      >
        {name}
      </Link>
      {a.specialization && (
        <span className="ml-2 text-xs text-slate-500">{a.specialization}</span>
      )}
      {(pick.note || a.bio) && (
        <p className="text-sm text-slate-400 mt-1 line-clamp-2">{pick.note || a.bio}</p>
      )}
      <Link href="/spotlight" className="inline-block mt-2 text-xs text-primary hover:underline">
        Past picks
      </Link>
    </div>
  );
}
