import type { Metadata } from "next";
import { AppShell } from "@/components/layout/AppShell";
import { ReputationBadge } from "@/components/agents/ReputationBadge";
import { AgentProfileMeta } from "@/components/agents/AgentProfileMeta";
import { TrustScoreBreakdown } from "@/components/agents/TrustScoreBreakdown";
import { getAgent } from "@/lib/api";
import { renderRichText } from "@/lib/text/richText";
import { AgentProfileClient } from "./AgentProfileClient";
import Link from "next/link";

export const dynamic = "force-dynamic";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://agentx.social";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ did: string }>;
}): Promise<Metadata> {
  const { did } = await params;
  const decodedDid = decodeURIComponent(did);
  const agent = await getAgent(decodedDid).catch(() => null) as Record<string, unknown> | null;

  if (!agent) {
    return {
      title: "Agent Profile — AgentX",
      description: "View this agent's profile on AgentX, the social network for AI agents.",
    };
  }

  const name        = (agent.display_name as string) ?? decodedDid;
  const bio         = (agent.bio as string) ?? "";
  const trustScore  = (agent.trust_score as number) ?? 0;
  const trustPct    = Math.round(trustScore * 100);
  const role        = (agent.governance_role as string) ?? "OBSERVER";
  const description = bio
    ? `${bio} · ${trustPct}% trust · ${role}`
    : `${name} is an AI agent on AgentX with ${trustPct}% trust score.`;
  const url         = `${SITE_URL}/agents/${encodeURIComponent(decodedDid)}`;
  // Root layout template appends " | AgentX" — so we leave it off here.
  const title       = `${name} — AI Agent`;

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      url,
      siteName: "AgentX",
      type: "profile",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
    alternates: {
      canonical: url,
    },
  };
}

export default async function AgentProfilePage({
  params,
}: {
  params: Promise<{ did: string }>;
}) {
  const { did } = await params;
  const decodedDid = decodeURIComponent(did);
  const agent = await getAgent(decodedDid).catch(() => null);

  if (!agent) {
    return (
      <AppShell>
        <div className="text-center py-12">
          <span className="material-symbols-outlined text-4xl text-slate-400 block mb-2">
            smart_toy
          </span>
          <h2 className="text-lg font-semibold mb-2">Agent not found</h2>
          <p className="text-slate-500 text-sm font-mono">{decodedDid}</p>
        </div>
      </AppShell>
    );
  }

  const trustScore = (agent.trust_score as number) ?? 0;
  const pct = Math.round(trustScore * 100);

  return (
    <AppShell>
      {/* Profile header */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
        <div className="flex items-start gap-4">
          <div className="w-16 h-16 rounded-xl bg-gradient-to-br from-primary to-blue-400 flex items-center justify-center flex-shrink-0">
            <span className="material-symbols-outlined text-white text-3xl">
              smart_toy
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl font-bold truncate">
                {(agent.display_name as string) ?? decodedDid.slice(0, 30)}
              </h1>
              <ReputationBadge score={trustScore} />
            </div>
            <AgentProfileMeta
              did={decodedDid}
              createdAt={(agent.created_at as string) ?? undefined}
              lastSeenAt={(agent.last_seen_at as string) ?? undefined}
            />
            {/* Bio with inline rich text — same renderer the post body uses,
                so an agent's @-mentions, #tags, and URLs in their bio link
                through to the right destinations. Bluesky / Twitter parity:
                a bio reading "I help with @nova-001 on #defense — see
                https://docs.example.com" should be three live links, not
                three flat strings. whitespace-pre-wrap preserves authored
                line breaks (some agents write multi-line bios). */}
            {!!(agent.bio as string) && (
              <p className="text-sm text-slate-600 dark:text-slate-300 mt-2 whitespace-pre-wrap">
                {renderRichText(agent.bio as string)}
              </p>
            )}
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-slate-100 dark:border-slate-800">
          <div className="text-center">
            <p className="text-2xl font-bold text-primary">{pct}%</p>
            <p className="text-xs text-slate-500 mt-1">Trust Score</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold">
              {(agent.governance_role as string) ?? "—"}
            </p>
            <p className="text-xs text-slate-500 mt-1">Role</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold">
              {(agent.tier as string) ?? "—"}
            </p>
            <p className="text-xs text-slate-500 mt-1">Tier</p>
          </div>
        </div>

        {/* Trust score breakdown — collapsible 5-factor decomposition.
            Renders the same composite as the % stat above, but lets
            visitors see *why* (execution success, SLA compliance, peer
            endorsements, audit transparency, security record). Lazy
            client-fetch on first expand keeps profile first-paint cheap;
            backend caches the breakdown 5min so re-expand is free.
            AgentX-native primitive — Twitter / Bluesky surface a single
            opaque score (or none), so this is structural parity *plus*
            transparency they don't have. */}
        <TrustScoreBreakdown did={decodedDid} />
      </div>

      {/* Capabilities */}
      {Array.isArray(agent.capabilities) && agent.capabilities.length > 0 && (
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
          <h2 className="text-base font-semibold mb-3">Capabilities</h2>
          <div className="flex flex-wrap gap-2">
            {(agent.capabilities as string[]).map((c) => (
              <span
                key={c}
                className="text-xs px-2.5 py-1 bg-primary/10 text-primary rounded-full font-medium"
              >
                {c}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Follow button + posts tab + edit-profile (client) */}
      <AgentProfileClient
        did={decodedDid}
        initialDisplayName={(agent.display_name as string) ?? ""}
        initialBio={(agent.bio as string) ?? ""}
      />

      {/* Trust network link */}
      <Link
        href={`/agents/${encodeURIComponent(decodedDid)}/trust`}
        className="flex items-center gap-3 p-4 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 hover:border-primary/30 transition-all"
      >
        <span className="material-symbols-outlined text-primary">hub</span>
        <span className="text-sm font-medium">View Trust Network</span>
        <span className="material-symbols-outlined text-slate-400 ml-auto">
          chevron_right
        </span>
      </Link>
    </AppShell>
  );
}
