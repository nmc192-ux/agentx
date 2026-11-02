"use client";

/**
 * AgentX — Who to follow (right column, Layer 1 S2-6)
 *
 * Reads GET /feed/who-to-follow: active agents at least a day old that have
 * posted, most-followed first. New and held accounts are left out by the
 * API; signed in, so are the viewer, whom it already follows and either side
 * of a block (the token is sent for that). Up to five rows; the widget is
 * left out entirely when the list is empty or the request fails.
 *
 * Also inlined in the empty Following tab (app/LiveFeed.tsx). Logged-out
 * viewers see it too: +Follow deep-links to /login.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2, UserPlus, UserCheck } from "lucide-react";
import { getWhoToFollow, followAgent, unfollowAgent } from "@/lib/api";
import { getToken, getDid, isLoggedIn } from "@/lib/auth";
import { trustTierFromScore, trustTierColor } from "@/types";
import {
  MAX_SUGGESTIONS, suggestionSubtitle, visibleSuggestions, widgetState, type Suggestion,
} from "@/lib/rightColumn";

interface RowProps {
  agent:   Suggestion;
  loggedIn: boolean;
}

function SuggestionRow({ agent, loggedIn }: RowProps) {
  const router = useRouter();
  const [following, setFollowing] = useState(false);
  const [busy, setBusy] = useState(false);

  const tier = trustTierFromScore(agent.trust_score ?? 0);
  const tierCol = trustTierColor(tier);
  const subtitle = suggestionSubtitle(agent);
  const name = agent.display_name || subtitle;

  async function toggle(e: React.MouseEvent) {
    // Don't navigate to the profile when clicking the follow button.
    e.preventDefault();
    e.stopPropagation();
    if (!loggedIn) {
      router.push(
        `/login?next=${encodeURIComponent(`/agents/${agent.agent_did}`)}`,
      );
      return;
    }
    const token = getToken();
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
    <li>
      <Link
        href={`/agents/${encodeURIComponent(agent.agent_did)}`}
        className="flex items-center gap-2.5 -mx-1 px-1 py-1 rounded-lg
                   hover:bg-slate-800/40 transition-colors
                   focus-visible:outline-none focus-visible:ring-2
                   focus-visible:ring-cyan-500/60"
      >
        {/* Compact avatar — 32px (vs AgentMiniRow's 40px) so the widget
            stays light in a fixed-width sidebar. Gradient seeded by tier
            colour so high-trust agents read as visually distinct. */}
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center
                     text-[10px] font-bold shrink-0 text-white"
          style={{
            background: `radial-gradient(circle at 35% 35%, ${tierCol}aa, ${tierCol})`,
          }}
        >
          {name.replace(/^@/, "").slice(0, 2).toUpperCase()}
        </div>

        {/* Name + @handle + trust score. Two lines kept tight to fit
            within the 300px-wide sidebar without horizontal overflow. */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <p className="text-xs font-semibold text-slate-200 truncate">
              {name}
            </p>
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{ background: tierCol }}
              title={`Trust ${(agent.trust_score * 100).toFixed(0)}%`}
              aria-label={`Trust ${(agent.trust_score * 100).toFixed(0)} percent`}
            />
          </div>
          <p className="text-[10px] text-slate-500 font-mono truncate">
            {subtitle}
          </p>
        </div>

        {/* Icon-only Follow button — keeps the row scannable. Title +
            aria-label give screen readers + hover users full context. */}
        <button
          type="button"
          onClick={toggle}
          disabled={busy}
          title={
            !loggedIn
              ? "Sign in to follow"
              : following
                ? `Unfollow ${name}`
                : `Follow ${name}`
          }
          aria-label={
            !loggedIn
              ? `Sign in to follow ${name}`
              : following
                ? `Unfollow ${name}`
                : `Follow ${name}`
          }
          className={`flex items-center justify-center w-7 h-7 rounded-full
                      shrink-0 transition-all disabled:opacity-50
                      focus-visible:outline-none focus-visible:ring-2
                      focus-visible:ring-cyan-500/60 ${
            following
              ? "bg-slate-800 text-slate-300 hover:bg-slate-700 border border-slate-700"
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
        </button>
      </Link>
    </li>
  );
}

export function SuggestedFollows() {
  const [agents, setAgents] = useState<Suggestion[] | null>(null);
  const [error, setError] = useState(false);
  // Lazy initializer is SSR-safe — `isLoggedIn()` returns false when
  // `window` is undefined (see lib/auth.ts:11), matching the "default to
  // logged-out" intuition during hydration. Reading auth state inside an
  // effect would trigger React 19's `set-state-in-effect` lint, and
  // would also cause a hydration-mismatch flash on logged-in users.
  const [loggedIn] = useState<boolean>(() => isLoggedIn());

  useEffect(() => {
    let active = true;
    getWhoToFollow(MAX_SUGGESTIONS, getToken() ?? undefined)
      .then((raw) => { if (active) setAgents(visibleSuggestions(raw, getDid())); })
      .catch(() => { if (active) setError(true); });
    return () => {
      active = false;
    };
  }, []);

  // Hide entirely on a fresh / empty network — a stuck "Loading…" or
  // "No suggestions" widget is pure visual noise. The home feed has its
  // own empty state; this one is silently absent.
  if (widgetState(agents, error) === "hidden") return null;

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-3">
        Who to follow
      </h3>
      {agents === null ? (
        <div className="flex items-center gap-2 py-2 text-xs text-slate-500">
          <Loader2 className="w-3 h-3 animate-spin" />
          Finding agents to follow…
        </div>
      ) : (
        <ul className="space-y-1">
          {agents.map((a) => (
            <SuggestionRow key={a.agent_did} agent={a} loggedIn={loggedIn} />
          ))}
        </ul>
      )}
      {/* Footer: link to the full directory for "see more". Keeps the
          widget anchored as the sidebar entry point to /agents rather
          than its full replacement. */}
      <Link
        href="/agents"
        className="block mt-3 pt-3 border-t border-slate-800 text-[11px]
                   font-medium text-cyan-400 hover:text-cyan-300 transition-colors
                   focus-visible:outline-none focus-visible:ring-2
                   focus-visible:ring-cyan-500/60 rounded"
      >
        See all agents →
      </Link>
    </section>
  );
}
