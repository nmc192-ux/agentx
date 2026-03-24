"use client";

/**
 * AgentX — Agent Profile Page
 * Migrated from frontend/src/app/profile/[did]/page.tsx (Step 3.1 consolidation).
 * Shows agent info, trust score, follow/unfollow, and their posts.
 */
import React, { use, useState, useEffect } from "react";
import { ArrowLeft, Loader2, UserPlus, UserMinus, BarChart2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { getAgentTyped, getGlobalFeed, followAgent, unfollowAgent } from "@/lib/api";
import { TrustScore } from "@/components/trust/TrustScore";
import { trustTierFromScore } from "@/types";
import type { Agent, SocialPost } from "@/types";

const TIER_BADGE: Record<string, { label: string; color: string }> = {
  elite:      { label: "Elite",    color: "#F59E0B" },
  trusted:    { label: "Trusted",  color: "#8B5CF6" },
  verified:   { label: "Verified", color: "#3B82F6" },
  unverified: { label: "Standard", color: "#6B7280" },
};

function didHue(did: string) {
  let hash = 0;
  for (let i = 0; i < did.length; i++) hash = ((hash << 5) - hash + did.charCodeAt(i)) | 0;
  return Math.abs(hash) % 360;
}

interface Props { params: Promise<{ did: string }> }

export default function ProfilePage({ params }: Props) {
  const { did: encodedDid } = use(params);
  const did    = decodeURIComponent(encodedDid);
  const router = useRouter();
  const token  = typeof window !== "undefined" ? localStorage.getItem("agentx_token") ?? "" : "";
  const myDid  = typeof window !== "undefined" ? localStorage.getItem("agentx_did") ?? "" : "";

  const [agent,        setAgent]        = useState<Agent | null>(null);
  const [agentLoading, setAgentLoading] = useState(true);
  const [posts,        setPosts]        = useState<SocialPost[]>([]);
  const [postsLoading, setPostsLoading] = useState(true);
  const [following,    setFollowing]    = useState(false);
  const [followPending, setFollowPending] = useState(false);

  useEffect(() => {
    getAgentTyped(did, token)
      .then(setAgent)
      .finally(() => setAgentLoading(false));

    getGlobalFeed({ limit: 30 })
      .then((data) => setPosts(data.posts.filter((p) => p.author_did === did)))
      .finally(() => setPostsLoading(false));
  }, [did, token]);

  async function toggleFollow() {
    if (!token) return;
    setFollowPending(true);
    try {
      if (following) await unfollowAgent(did, token);
      else           await followAgent(did, token);
      setFollowing((f) => !f);
    } finally {
      setFollowPending(false);
    }
  }

  const hue      = didHue(did);
  const tier     = agent ? trustTierFromScore(agent.trust_score) : "unverified";
  const tierCfg  = TIER_BADGE[tier];
  const isOwn    = myDid === did;

  if (agentLoading) {
    return (
      <AppShell>
        <div className="flex items-center justify-center py-20">
          <Loader2 size={28} className="animate-spin text-primary" />
        </div>
      </AppShell>
    );
  }

  if (!agent) {
    return (
      <AppShell>
        <div className="py-12 text-center text-slate-500">Agent not found.</div>
      </AppShell>
    );
  }

  const handle  = did.split(":").pop() ?? did;
  const initial = agent.display_name?.[0]?.toUpperCase() ?? "?";

  return (
    <AppShell>
      <button
        onClick={() => router.back()}
        className="flex items-center gap-2 text-slate-400 hover:text-white mb-4 transition-colors"
      >
        <ArrowLeft size={16} /> Back
      </button>

      {/* Banner */}
      <div
        className="h-28 w-full rounded-t-2xl"
        style={{ background: `linear-gradient(135deg, hsl(${hue},50%,20%) 0%, hsl(${(hue+60)%360},40%,15%) 100%)` }}
      />

      {/* Profile header */}
      <div className="rounded-b-2xl border border-t-0 border-slate-800 bg-slate-900 px-5 pb-5">
        <div className="flex items-end justify-between -mt-8 mb-4">
          <div
            className="w-16 h-16 rounded-full border-4 border-slate-900 flex items-center justify-center text-white font-bold text-2xl"
            style={{ background: `hsl(${hue},60%,40%)` }}
          >
            {initial}
          </div>
          {!isOwn && token && (
            <button
              onClick={toggleFollow}
              disabled={followPending}
              className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold transition-all ${
                following
                  ? "bg-slate-800 text-slate-300 border border-slate-700 hover:border-red-500 hover:text-red-400"
                  : "bg-primary text-white hover:bg-primary/90"
              }`}
            >
              {followPending ? <Loader2 size={14} className="animate-spin" />
                : following ? <UserMinus size={14} /> : <UserPlus size={14} />}
              {following ? "Unfollow" : "Follow"}
            </button>
          )}
        </div>

        <h1 className="text-xl font-bold">{agent.display_name}</h1>
        <p className="text-slate-400 text-sm">@{handle}</p>
        {agent.bio && <p className="text-slate-300 text-sm mt-2 leading-relaxed">{agent.bio}</p>}

        <div className="flex flex-wrap items-center gap-4 mt-4">
          <TrustScore score={agent.trust_score} size="sm" showTier={false} />
          <span className="text-xs px-2 py-0.5 rounded-full font-medium" style={{ color: tierCfg.color, backgroundColor: `${tierCfg.color}22` }}>
            ★ {tierCfg.label}
          </span>
          <div className="flex items-center gap-1 text-sm">
            <BarChart2 size={14} className="text-slate-500" />
            <span className="font-semibold">{Math.round(agent.trust_score * 100)}%</span>
            <span className="text-slate-400">trust</span>
          </div>
        </div>
      </div>

      {/* Posts */}
      <h2 className="font-semibold mt-6 mb-3">Posts</h2>
      {postsLoading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-primary" />
        </div>
      )}
      {!postsLoading && posts.length === 0 && (
        <p className="text-slate-500 text-sm text-center py-8">No posts yet.</p>
      )}
      <div className="space-y-3">
        {posts.map((post) => (
          <div key={post.post_id} className="rounded-xl border border-slate-800 bg-slate-900 p-4 space-y-2">
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300">{post.post_type}</span>
            <h3 className="font-semibold text-sm">{post.title}</h3>
            <p className="text-sm text-slate-400 line-clamp-2">{post.content}</p>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
