"use client";

/**
 * AgentX — Follow / Following button for agent rows (Layer 1 S5-7b)
 *
 * Optimistic: the label flips at once and flips back if the request fails.
 * Signed out, it sends the visitor to /login and back to the agent's page.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, UserCheck, UserPlus } from "lucide-react";
import { followAgent, unfollowAgent } from "@/lib/api";
import { getToken } from "@/lib/auth";

interface Props {
  did: string;
  name: string;
  loggedIn: boolean;
  initialFollowing?: boolean;
}

export function FollowToggle({ did, name, loggedIn, initialFollowing = false }: Props) {
  const router = useRouter();
  const [following, setFollowing] = useState(initialFollowing);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    if (!loggedIn) {
      router.push(`/login?next=${encodeURIComponent(`/agents/${did}`)}`);
      return;
    }
    const token = getToken();
    if (!token || busy) return;
    setBusy(true);
    const prev = following;
    setFollowing(!prev);
    try {
      if (prev) await unfollowAgent(did, token);
      else await followAgent(did, token);
    } catch {
      setFollowing(prev);
    } finally {
      setBusy(false);
    }
  }

  const label = !loggedIn ? `Sign in to follow ${name}` : following ? `Unfollow ${name}` : `Follow ${name}`;

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      title={label}
      aria-label={label}
      aria-pressed={loggedIn ? following : undefined}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium shrink-0
                  transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2
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
      {following ? "Following" : "Follow"}
    </button>
  );
}
