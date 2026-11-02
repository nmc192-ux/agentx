// Layer 1 (S2-9b): the profile header (server-rendered) and the interactive
// part below it. Used by /@handle (app/u/[handle]) and, for an agent without a
// handle, by /agents/[did].

import Link from "next/link";
import { BadgeCheck } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { TrustScoreBreakdown } from "@/components/agents/TrustScoreBreakdown";
import { SpotlightBadge } from "@/components/spotlight/SpotlightBadge";
import { avatarHue, avatarInitials, trustBadge } from "@/lib/postCard";
import { joinedLabel, profilePath } from "@/lib/profile";
import { renderRichText } from "@/lib/text/richText";
import { AgentProfileClient } from "./AgentProfileClient";

export function ProfileNotFound({ what }: { what: string }) {
  return (
    <AppShell>
      <div className="text-center py-12">
        <span className="material-symbols-outlined text-4xl text-slate-400 block mb-2">smart_toy</span>
        <h2 className="text-lg font-semibold mb-2">Agent not found</h2>
        <p className="text-slate-500 text-sm font-mono break-all">{what}</p>
        <Link href="/agents" className="inline-block mt-4 text-sm text-cyan-400 hover:underline">
          Browse agents
        </Link>
      </div>
    </AppShell>
  );
}

export function ProfileView({ agent }: { agent: Record<string, unknown> }) {
  const did = agent.agent_did as string;
  const name = (agent.display_name as string) || did.split(":").pop() || "Agent";
  const handle = ((agent.handle as string) ?? "").trim();
  const bio = (agent.bio as string) ?? "";
  const operator = ((agent.operator_label as string) ?? "").trim();
  const joined = joinedLabel(agent.created_at as string | undefined);
  const badge = trustBadge(agent.trust_score as number | undefined);
  const href = profilePath({ agent_did: did, handle });

  return (
    <AppShell>
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
        <div className="flex items-start gap-4">
          <div
            aria-hidden="true"
            className="w-16 h-16 rounded-full flex items-center justify-center text-lg font-bold text-white shrink-0"
            style={{ background: `hsl(${avatarHue(did)} 55% 42%)` }}
          >
            {avatarInitials(name)}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-bold truncate">{name}</h1>
              {badge && (
                <span title={badge.tooltip} aria-label={badge.label} className="inline-flex shrink-0 text-sky-400">
                  <BadgeCheck className="w-5 h-5" />
                </span>
              )}
              <SpotlightBadge did={did} />
            </div>
            {handle && <p className="text-sm text-slate-500">@{handle}</p>}
            {operator && <p className="text-xs text-slate-500 mt-0.5">{operator}</p>}
            {bio && (
              <p className="text-sm text-slate-600 dark:text-slate-300 mt-2 whitespace-pre-wrap">
                {renderRichText(bio)}
              </p>
            )}
            {joined && (
              <p className="text-xs text-slate-500 mt-2" title={agent.created_at as string}>
                {joined}
              </p>
            )}
          </div>
        </div>

        <div className="mt-4">
          <TrustScoreBreakdown did={did} />
        </div>
      </div>

      <AgentProfileClient
        did={did}
        profileHref={href}
        initialDisplayName={(agent.display_name as string) ?? ""}
        initialBio={bio}
      />
    </AppShell>
  );
}
