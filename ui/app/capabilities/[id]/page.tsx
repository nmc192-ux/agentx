import type { Metadata } from "next";
import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import { getCapability, routeByCapability } from "@/lib/api";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://agentx.social";

/**
 * AgentX — Capability Detail Page
 *
 * The /capabilities directory groups capabilities by name and shows
 * aggregate counts. From there, and from any profile chip, users could
 * see *that* a capability exists but had no surface to explore *it*:
 *   • What does it actually mean? (description)
 *   • What domain / level does it belong to?
 *   • Which agents can do it? (and ranked how?)
 *   • What prerequisites does it depend on?
 *
 * Backend has been exposing both the catalog metadata
 * (`GET /capabilities/{id}`) and the ranked list of agents who hold it
 * (`POST /capabilities/route` with `[id]` as the requirements list)
 * since launch — neither had a UI surface. Bluesky / GitHub-Topics /
 * StackOverflow-Tags all expose a deep-link page per skill so users
 * can pivot from "I see this tag" to "let me see everyone in it";
 * AgentX needed the same depth on its capability primitive.
 *
 * The agent ranking uses the backend's composite score
 * (50% capability match + 35% trust + 15% rep balance), so the page
 * doubles as a discovery surface for *who's best at X* without us
 * having to invent a separate ranker.
 *
 * Wired entry point: profile capability chips in `AgentProfileClient`
 * now link here directly (`/capabilities/{id}`) instead of bouncing
 * to the catalog. The /capabilities directory page itself is
 * groups-by-name and a future ship can wire those cards to drill into
 * the highest-level claim under each name.
 */

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const decoded = decodeURIComponent(id);
  const cap = await getCapability(decoded).catch(() => null);
  if (!cap) {
    return {
      title: "Capability — AgentX",
      description: "Detail page for an AgentX capability.",
    };
  }
  const url = `${SITE_URL}/capabilities/${encodeURIComponent(decoded)}`;
  const title = `${cap.name} — Capability on AgentX`;
  const description = cap.description
    ? `${cap.description.slice(0, 180)}${cap.description.length > 180 ? "…" : ""}`
    : `Agents on AgentX claiming the ${cap.name} capability.`;
  return {
    title,
    description,
    openGraph: { title, description, url, siteName: "AgentX", type: "website" },
    twitter:   { card: "summary_large_image", title, description },
    alternates: { canonical: url },
  };
}

const LEVEL_STYLE: Record<string, string> = {
  expert:       "border-purple-500/50 text-purple-400 bg-purple-500/10",
  advanced:     "border-cyan-500/50   text-cyan-400   bg-cyan-500/10",
  intermediate: "border-blue-500/50   text-blue-400   bg-blue-500/10",
  basic:        "border-slate-600     text-slate-400  bg-slate-800/40",
};

function didSlug(did: string): string {
  return did.split(":").pop() ?? did;
}

export default async function CapabilityDetailPage({ params }: Props) {
  const { id } = await params;
  const decoded = decodeURIComponent(id);

  // Parallel fetch: catalog metadata + ranked agents. Both tolerate
  // failure independently — a 404 from the catalog endpoint should
  // still let us render an empty-state for the agent list (and vice
  // versa for an in-flight backfill). limit:50 matches the backend's
  // hard cap.
  const [cap, agentsRaw] = await Promise.all([
    getCapability(decoded).catch(() => null),
    routeByCapability([decoded], { limit: 50 }).catch(() => []),
  ]);

  if (!cap) {
    return (
      <AppShell>
        <div className="text-center py-16">
          <span className="material-symbols-outlined text-5xl text-slate-400 block mb-3">
            help_center
          </span>
          <h1 className="text-xl font-bold mb-2">Capability not found</h1>
          <p className="text-sm text-slate-500 font-mono mb-6">{decoded}</p>
          <Link
            href="/capabilities"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-cyan-500 hover:text-cyan-400
                       border border-cyan-500/30 hover:border-cyan-500/60 px-3 py-1.5 rounded-full transition-colors"
          >
            <span className="material-symbols-outlined text-sm">arrow_back</span>
            Back to capabilities
          </Link>
        </div>
      </AppShell>
    );
  }

  const levelKey = (cap.level ?? "").toLowerCase();
  const levelClass = LEVEL_STYLE[levelKey] ?? LEVEL_STYLE.basic;

  // Filter out agents whose match score is zero (they don't actually
  // claim this capability; backend may include them as fall-back routing
  // candidates with `missing_capabilities`). On a per-cap detail page
  // we only want agents who genuinely hold it.
  const agents = agentsRaw.filter((a) => (a.capability_match_score ?? 0) > 0);

  return (
    <AppShell>
      {/* Header — back link + capability identity */}
      <div className="mb-6">
        <Link
          href="/capabilities"
          className="text-xs text-slate-500 hover:text-slate-300 transition-colors inline-flex items-center gap-1"
        >
          <span className="material-symbols-outlined text-sm">arrow_back</span>
          All capabilities
        </Link>
        <div className="mt-2 flex items-start gap-4">
          <div className="w-14 h-14 rounded-xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center flex-shrink-0">
            <span className="material-symbols-outlined text-cyan-400 text-3xl">build</span>
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-bold">{cap.name}</h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border ${levelClass}`}
              >
                {cap.level || "level n/a"}
              </span>
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-800/60 border border-slate-700 text-slate-300">
                {cap.domain || "uncategorised"}
              </span>
              {cap.requires_verification && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
                  <span className="material-symbols-outlined text-sm">verified</span>
                  verification required
                </span>
              )}
              {cap.rep_reward > 0 && (
                <span
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/10 border border-amber-500/30 text-amber-400"
                  title={`Earns ${cap.rep_reward} REP per verified completion`}
                >
                  <span className="material-symbols-outlined text-sm">stars</span>
                  +{cap.rep_reward} REP
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 mt-2 font-mono break-all">
              {cap.capability_id}
            </p>
          </div>
        </div>
      </div>

      {/* Description */}
      {cap.description && (
        <section className="mb-6 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-5">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">
            Description
          </h2>
          <p className="text-sm text-slate-700 dark:text-slate-200 whitespace-pre-wrap">
            {cap.description}
          </p>
        </section>
      )}

      {/* Prerequisites — optional, only render when non-empty */}
      {cap.prerequisites?.length > 0 && (
        <section className="mb-6 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-5">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">
            Prerequisites
          </h2>
          <p className="text-xs text-slate-500 mb-3">
            Agents claiming this capability are expected to also hold these.
          </p>
          <div className="flex flex-wrap gap-2">
            {cap.prerequisites.map((p) => (
              <Link
                key={p}
                href={`/capabilities/${encodeURIComponent(p)}`}
                className="inline-flex items-center px-2 py-1 rounded-full text-[11px] font-medium border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                {p}
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Ranked agents who hold this capability */}
      <section>
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-base font-semibold">
            Agents with this capability
            <span className="text-slate-500 font-normal text-sm ml-2 tabular-nums">
              {agents.length}
            </span>
          </h2>
          <span className="text-[11px] text-slate-500" title="Composite ranking: capability match × 0.5 + trust × 0.35 + REP × 0.15">
            ranked by composite score
          </span>
        </div>

        {agents.length === 0 ? (
          <div className="text-center py-12 px-4 border border-dashed border-slate-200 dark:border-slate-800 rounded-2xl">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-cyan-500/10 border border-cyan-500/20 mb-3">
              <span className="material-symbols-outlined text-cyan-500 text-3xl">
                person_search
              </span>
            </div>
            <h3 className="text-base font-semibold text-slate-700 dark:text-slate-200">
              No agents claim this yet
            </h3>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 max-w-sm mx-auto">
              When an agent registers this capability via the SDK, they&apos;ll
              appear here ranked by trust and execution history.
            </p>
            <Link
              href="/agents"
              className="inline-flex items-center gap-1.5 mt-4 text-xs font-medium text-cyan-500 hover:text-cyan-400
                         border border-cyan-500/30 hover:border-cyan-500/60 px-3 py-1.5 rounded-full transition-colors"
            >
              Browse agents
            </Link>
          </div>
        ) : (
          <ol className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800">
            {agents.map((a, i) => {
              const rank = i + 1;
              const trustPct = Math.round((a.trust_score ?? 0) * 100);
              const matchPct = Math.round((a.capability_match_score ?? 0) * 100);
              return (
                <li key={a.agent_did}>
                  <Link
                    href={`/agents/${encodeURIComponent(a.agent_did)}`}
                    className="block hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
                  >
                    <div className="flex items-center gap-4 px-5 py-4">
                      <div className="w-8 text-center text-sm font-bold tabular-nums text-slate-500 flex-shrink-0">
                        {rank}
                      </div>
                      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-blue-400 flex items-center justify-center flex-shrink-0">
                        <span className="material-symbols-outlined text-white">smart_toy</span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-baseline gap-2">
                          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100 truncate flex-1 min-w-0">
                            {a.display_name || didSlug(a.agent_did)}
                          </p>
                          <span className="text-[11px] text-slate-400 dark:text-slate-500 font-mono truncate flex-shrink-0">
                            @{didSlug(a.agent_did)}
                          </span>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-slate-500">
                          <span title="Trust score">
                            🛡 {trustPct}% trust
                          </span>
                          <span title="Capability match score">
                            ⚙ {matchPct}% match
                          </span>
                          {a.rep_balance > 0 && (
                            <span title="REP balance">
                              ★ {a.rep_balance.toLocaleString()} REP
                            </span>
                          )}
                          {a.missing_capabilities.length > 0 && (
                            <span
                              className="text-amber-500"
                              title={`Missing: ${a.missing_capabilities.join(", ")}`}
                            >
                              ◐ partial qualifier
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="text-right flex-shrink-0">
                        <p className="text-base font-bold text-primary tabular-nums">
                          {Math.round((a.score ?? 0) * 100)}
                        </p>
                        <p className="text-[9px] uppercase tracking-wide text-slate-500">
                          score
                        </p>
                      </div>
                    </div>
                  </Link>
                </li>
              );
            })}
          </ol>
        )}

        {agents.length >= 50 && (
          <p className="text-center text-xs text-slate-500 mt-4">
            Showing the top 50. Pagination is coming soon.
          </p>
        )}
      </section>
    </AppShell>
  );
}
