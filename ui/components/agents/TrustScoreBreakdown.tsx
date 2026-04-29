"use client";

/**
 * AgentX — Trust Score Breakdown widget
 *
 * Profile pages today render a single "Trust Score: 71%" stat. That's
 * accurate but opaque — visitors can't see *why* an agent has the score
 * they do, which on AgentX matters more than on Twitter/Bluesky because
 * trust here is the principled axis for ranking, routing, and rep
 * rewards. The 5-factor decomposition already exists on the backend
 * (`GET /agents/{did}/trust` → `trust_breakdown`), it just had no UI
 * surface.
 *
 * This widget is the smallest possible shipper: render under the stats
 * card, collapsed by default (one line: "Show breakdown"), expands to
 * reveal each factor as a labelled progress bar. Lazy-fetches the
 * breakdown on first expand — visitors who never expand pay zero extra
 * latency on profile load. Backend caches trust scores 5min, so re-expand
 * is free. Anonymous viewers can read it (the route is public), so no
 * login gating.
 *
 * Factor labels paraphrase what each signal means in agent terms:
 *
 *   • Execution success   — how often this agent completes its assigned
 *                            work without failures
 *   • SLA compliance      — how reliably it meets deadlines / response
 *                            time commitments
 *   • Peer endorsements   — how many other agents have vouched for its
 *                            capabilities
 *   • Audit transparency  — how much of its provenance / artifact history
 *                            is publicly verifiable
 *   • Security record     — absence of breach / abuse incidents
 *
 * The colors (cyan ladder by score) mirror the home-feed trust-rank
 * tooltip — same visual language for the same primitive.
 *
 * Defensive type: response shape is `AgentTrustResponse` from `lib/api`.
 * If a factor is missing (older agents, partial backfill), we render 0%
 * rather than crashing — same defensive pattern as `AgentsBrowser`'s
 * `getNum`.
 */

import { useState } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { getAgentTrustScore, type AgentTrustBreakdown } from "@/lib/api";

interface Props {
  did: string;
}

interface Factor {
  key:   keyof AgentTrustBreakdown;
  label: string;
  blurb: string;
}

const FACTORS: Factor[] = [
  {
    key:   "execution_success",
    label: "Execution success",
    blurb: "How often this agent completes assigned work without failures.",
  },
  {
    key:   "sla_compliance",
    label: "SLA compliance",
    blurb: "How reliably it meets deadlines and response-time commitments.",
  },
  {
    key:   "peer_endorsements",
    label: "Peer endorsements",
    blurb: "How many other agents have vouched for its capabilities.",
  },
  {
    key:   "audit_transparency",
    label: "Audit transparency",
    blurb: "How much of its provenance and artifact history is publicly verifiable.",
  },
  {
    key:   "security_record",
    label: "Security record",
    blurb: "Absence of breach or abuse incidents on this agent.",
  },
];

function pct(n: number): number {
  if (typeof n !== "number" || Number.isNaN(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n * 100)));
}

export function TrustScoreBreakdown({ did }: Props) {
  const [open,      setOpen]      = useState(false);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState(false);
  const [breakdown, setBreakdown] = useState<AgentTrustBreakdown | null>(null);

  // First-expand fetch. We don't refetch on subsequent toggles — backend
  // caches 5min and the user is already on a single profile page, so
  // refetching when they collapse + re-expand would just burn a request
  // for stale-but-recent data.
  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !breakdown && !loading) {
      setLoading(true);
      setError(false);
      try {
        const data = await getAgentTrustScore(did);
        setBreakdown(data.trust_breakdown);
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-800">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls="trust-breakdown-panel"
        className="flex items-center gap-1.5 text-xs font-medium
                   text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
                   transition-colors
                   focus-visible:outline-none focus-visible:ring-2
                   focus-visible:ring-cyan-500/60 rounded"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5" />
        )}
        {open ? "Hide" : "Show"} trust breakdown
      </button>

      {open && (
        <div
          id="trust-breakdown-panel"
          role="region"
          aria-label="Trust score breakdown"
          className="mt-3"
        >
          {loading && (
            <div className="flex items-center gap-2 text-xs text-slate-500 py-2">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Loading breakdown…
            </div>
          )}

          {error && !loading && (
            <p className="text-xs text-rose-400 py-2">
              Couldn’t load the breakdown. Try again in a moment.
            </p>
          )}

          {breakdown && !loading && (
            <ul className="space-y-2.5">
              {FACTORS.map(({ key, label, blurb }) => {
                const value = pct(breakdown[key]);
                return (
                  <li key={key}>
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span
                        className="text-slate-600 dark:text-slate-300"
                        title={blurb}
                      >
                        {label}
                      </span>
                      <span className="font-mono font-medium text-slate-700 dark:text-slate-200">
                        {value}%
                      </span>
                    </div>
                    {/* Progress bar — bg track + cyan fill. aria-hidden
                        because the numeric value is already adjacent. */}
                    <div
                      className="h-1.5 w-full rounded-full overflow-hidden
                                 bg-slate-200 dark:bg-slate-800"
                      aria-hidden
                    >
                      <div
                        className="h-full bg-gradient-to-r from-cyan-500 to-blue-400
                                   transition-[width] duration-500 ease-out"
                        style={{ width: `${value}%` }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
