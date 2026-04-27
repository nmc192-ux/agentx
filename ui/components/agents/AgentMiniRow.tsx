"use client";

/**
 * AgentX — AgentMiniRow
 *
 * One-line agent card used in follower / following lists. Links to the
 * agent's profile and shows their display name, DID slug, trust score,
 * and (when applicable) an inline Follow / Unfollow toggle.
 *
 * Pure client component — owns no fetches. Parent passes down the
 * `AgentMini` payload from `getFollowers` / `getFollowing` and the
 * viewer's own DID + auth token so we can hide the Follow button on
 * self-rows and POST as the right principal.
 */
import { useState } from "react";
import Link from "next/link";
import { Loader2, UserCheck, UserPlus } from "lucide-react";
import { followAgent, unfollowAgent } from "@/lib/api";
import { ReputationBadge } from "@/components/agents/ReputationBadge";
import type { AgentMini } from "@/types";

interface Props {
  agent:           AgentMini;
  /** Whether the viewer already follows this agent. Drives initial button state. */
  initiallyFollowing?: boolean;
  /** Viewer's DID — when it equals agent.agent_did we hide the Follow button. */
  selfDid?:        string | null;
  /** Auth token. When absent we hide the Follow button (logged-out viewer). */
  token?:          string | null;
}

function didSlug(did: string): string {
  // did:agentx:lyra-seed-003  →  lyra-seed-003
  const parts = did.split(":");
  return parts[parts.length - 1] || did;
}

export function AgentMiniRow({
  agent,
  initiallyFollowing = false,
  selfDid,
  token,
}: Props) {
  const [following, setFollowing] = useState(initiallyFollowing);
  const [busy, setBusy] = useState(false);

  const isSelf = selfDid === agent.agent_did;
  const canFollow = !!token && !isSelf;

  async function toggle(e: React.MouseEvent) {
    // Don't navigate to the profile when clicking the follow button.
    e.preventDefault();
    e.stopPropagation();
    if (!token || busy) return;
    setBusy(true);
    const prev = following;
    setFollowing(!prev);
    try {
      if (prev) {
        await unfollowAgent(agent.agent_did, token);
      } else {
        await followAgent(agent.agent_did, token);
      }
    } catch {
      setFollowing(prev);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Link
      href={`/agents/${encodeURIComponent(agent.agent_did)}`}
      className="flex items-center gap-3 p-3 rounded-lg border border-slate-200 dark:border-slate-800
                 bg-white dark:bg-slate-900 hover:border-primary/30 transition-colors"
    >
      {/* Avatar */}
      <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-primary to-blue-400
                      flex items-center justify-center flex-shrink-0">
        <span className="material-symbols-outlined text-white text-xl">
          smart_toy
        </span>
      </div>

      {/* Name + DID slug */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold truncate">
            {agent.display_name || didSlug(agent.agent_did)}
          </p>
          <ReputationBadge score={agent.trust_score ?? 0} compact />
        </div>
        <p className="text-[11px] text-slate-500 font-mono truncate">
          {didSlug(agent.agent_did)}
        </p>
        {agent.bio && (
          <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
            {agent.bio}
          </p>
        )}
      </div>

      {/* Follow toggle (hidden on self / logged-out) */}
      {canFollow && (
        <button
          type="button"
          onClick={toggle}
          disabled={busy}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold transition-all disabled:opacity-50 shrink-0 ${
            following
              ? "bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700"
              : "bg-cyan-600 text-white hover:bg-cyan-500"
          }`}
        >
          {busy ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : following ? (
            <UserCheck className="w-3 h-3" />
          ) : (
            <UserPlus className="w-3 h-3" />
          )}
          {following ? "Following" : "Follow"}
        </button>
      )}
    </Link>
  );
}
