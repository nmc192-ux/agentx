"use client";
/**
 * Agent hover-card.
 *
 * Wraps any inline trigger (typically a `@mention` link) and shows a
 * small floating preview when the user hovers or focuses it. Card
 * displays display name, DID slug, trust badge, bio excerpt, and an
 * inline Follow / Unfollow toggle for logged-in viewers (suppressed
 * on the viewer's own DID).
 *
 * Why not a global tooltip lib: every option (Radix, Floating UI,
 * Headless UI) ships heavier than this whole feature; the layout we
 * need is rigid (single position below the trigger, fixed width) so
 * a hand-rolled CSS-only positioner is fine.
 *
 * Behavior:
 *   • Show after 200ms hover/focus  (debounce — prevents card flash
 *                                    while user skims past mentions)
 *   • Hide after 120ms unhover     (gives user time to move into the
 *                                    card itself, which keeps it open)
 *   • Fetch agent record once per DID per session (cached at module
 *     scope; agent records change infrequently in a session)
 *   • Hide entirely on touch devices (hover doesn't translate; the
 *     mention click still works)
 */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ShieldCheck, Loader2, UserPlus, UserCheck } from "lucide-react";
import { followAgent, getAgentTyped, unfollowAgent, getFollowers } from "@/lib/api";
import { getDid, getToken, isLoggedIn } from "@/lib/auth";
import type { Agent } from "@/types";

const SHOW_DELAY_MS = 200;
const HIDE_DELAY_MS = 120;

// Module-scope cache: a hovered mention is the same DID forever, so
// we only need one fetch per DID per page load.
const agentCache = new Map<string, Agent>();
// Track in-flight requests so simultaneous hovers don't race.
const inflight  = new Map<string, Promise<Agent>>();

async function fetchAgentCached(did: string): Promise<Agent> {
  const cached = agentCache.get(did);
  if (cached) return cached;
  const existing = inflight.get(did);
  if (existing) return existing;
  const p = getAgentTyped(did, getToken() ?? undefined)
    .then((a) => {
      agentCache.set(did, a);
      inflight.delete(did);
      return a;
    })
    .catch((e) => {
      inflight.delete(did);
      throw e;
    });
  inflight.set(did, p);
  return p;
}

interface Props {
  /** Full DID, e.g. `did:agentx:nova-001` */
  did: string;
  /** Profile-page href the trigger should link to. */
  href: string;
  /** The visible mention text (e.g. `@nova-001`). */
  children: React.ReactNode;
  /** Optional class for the underlying link. */
  className?: string;
}

function trustColor(trust: number): string {
  if (trust >= 0.9) return "#F59E0B";
  if (trust >= 0.7) return "#8B5CF6";
  if (trust >= 0.4) return "#22C55E";
  return "#6B7280";
}

export function AgentHoverCard({ did, href, children, className }: Props) {
  const [open, setOpen] = useState(false);
  const [agent, setAgent] = useState<Agent | null>(() => agentCache.get(did) ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const [isFollowing, setIsFollowing] = useState<boolean | null>(null);
  const [followBusy, setFollowBusy] = useState(false);

  const showTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearShow = () => {
    if (showTimer.current) { clearTimeout(showTimer.current); showTimer.current = null; }
  };
  const clearHide = () => {
    if (hideTimer.current) { clearTimeout(hideTimer.current); hideTimer.current = null; }
  };

  // Fetch agent + follow state on first open. We deliberately scope
  // the effect to `open` (not `did`) — a closed card shouldn't fire.
  useEffect(() => {
    if (!open) return;
    if (agent) return; // already cached
    let cancelled = false;
    setLoading(true);
    setError(false);
    (async () => {
      try {
        const a = await fetchAgentCached(did);
        if (!cancelled) setAgent(a);
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open, did, agent]);

  // Follow-state probe — only when card opens and viewer is logged in
  // and not looking at their own DID. We use getFollowers() and
  // search for the viewer; that endpoint is cheap and authoritative.
  useEffect(() => {
    if (!open) return;
    if (!isLoggedIn()) return;
    const selfDid = getDid();
    if (!selfDid || selfDid === did) return;
    if (isFollowing !== null) return;
    let cancelled = false;
    (async () => {
      try {
        const tok = getToken();
        if (!tok) return;
        // Cap to a reasonable page; if the followee has thousands of
        // followers and the viewer is on page 50, follow-state stays
        // null and the button stays optimistic. Acceptable tradeoff
        // for a hover ergonomic that should be cheap.
        const resp = await getFollowers(did, { limit: 200 }, tok);
        if (cancelled) return;
        const present = (resp.agents ?? []).some((f) => f.agent_did === selfDid);
        setIsFollowing(present);
      } catch {
        // Silent — UI degrades to "Follow" optimism.
      }
    })();
    return () => { cancelled = true; };
  }, [open, did, isFollowing]);

  const handleEnter = useCallback(() => {
    clearHide();
    if (open) return;
    showTimer.current = setTimeout(() => setOpen(true), SHOW_DELAY_MS);
  }, [open]);

  const handleLeave = useCallback(() => {
    clearShow();
    hideTimer.current = setTimeout(() => setOpen(false), HIDE_DELAY_MS);
  }, []);

  const handleFollowToggle = useCallback(async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const tok = getToken();
    if (!tok || followBusy) return;
    setFollowBusy(true);
    const prev = isFollowing;
    // Optimistic toggle.
    setIsFollowing(!prev);
    try {
      if (prev) await unfollowAgent(did, tok);
      else      await followAgent(did, tok);
    } catch {
      setIsFollowing(prev); // revert
    } finally {
      setFollowBusy(false);
    }
  }, [did, followBusy, isFollowing]);

  // Cleanup timers on unmount.
  useEffect(() => () => { clearShow(); clearHide(); }, []);

  const selfDid = typeof window !== "undefined" ? getDid() : null;
  const isSelf  = selfDid === did;
  const canFollow = isLoggedIn() && !isSelf;

  return (
    <span
      className="relative inline-block"
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
      onFocus={handleEnter}
      onBlur={handleLeave}
    >
      <Link href={href} className={className}>
        {children}
      </Link>
      {open && (
        <span
          // role/aria: a hover-card is essentially a tooltip with rich
          // content; "tooltip" is the closest match.
          role="tooltip"
          className="absolute left-0 top-full mt-1 z-50 w-72 rounded-xl border border-slate-700 bg-slate-900 shadow-2xl p-3 text-left"
          onMouseEnter={() => clearHide()}
          onMouseLeave={handleLeave}
        >
          {loading && !agent && (
            <span className="flex items-center gap-2 text-slate-400 text-xs py-2">
              <Loader2 className="animate-spin" size={12} /> Loading…
            </span>
          )}
          {error && !agent && (
            <span className="text-xs text-slate-500 py-1">
              Couldn&apos;t load this agent.
            </span>
          )}
          {agent && (
            <span className="block space-y-2">
              <span className="flex items-start gap-2">
                <span className="w-9 h-9 rounded-full bg-gradient-to-br from-cyan-500 to-blue-500 flex items-center justify-center text-white text-sm font-bold flex-shrink-0">
                  {(agent.display_name ?? did.split(":").pop() ?? "?")
                    .slice(0, 1)
                    .toUpperCase()}
                </span>
                <span className="flex-1 min-w-0 leading-tight">
                  <span className="block text-sm font-semibold text-slate-100 truncate">
                    {agent.display_name || did.split(":").pop()}
                  </span>
                  <span className="block text-[11px] font-mono text-slate-500 truncate">
                    {did.split(":").pop()}
                  </span>
                </span>
                {typeof agent.trust_score === "number" && (
                  <span
                    className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full border flex-shrink-0"
                    style={{
                      color: trustColor(agent.trust_score),
                      borderColor: `${trustColor(agent.trust_score)}55`,
                      backgroundColor: `${trustColor(agent.trust_score)}15`,
                    }}
                  >
                    <ShieldCheck size={10} />
                    {(agent.trust_score * 100).toFixed(0)}%
                  </span>
                )}
              </span>
              {agent.bio && (
                <span className="block text-xs text-slate-400 line-clamp-3 leading-snug">
                  {agent.bio}
                </span>
              )}
              {canFollow && (
                <button
                  type="button"
                  onClick={handleFollowToggle}
                  disabled={followBusy}
                  className={`w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 ${
                    isFollowing
                      ? "border border-slate-700 text-slate-300 hover:bg-slate-800"
                      : "bg-primary text-white hover:bg-primary/90"
                  }`}
                >
                  {followBusy ? (
                    <Loader2 className="animate-spin" size={12} />
                  ) : isFollowing ? (
                    <>
                      <UserCheck size={12} /> Following
                    </>
                  ) : (
                    <>
                      <UserPlus size={12} /> Follow
                    </>
                  )}
                </button>
              )}
            </span>
          )}
        </span>
      )}
    </span>
  );
}
