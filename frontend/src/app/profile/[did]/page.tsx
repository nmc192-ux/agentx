"use client";
import { use } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, UserPlus, UserMinus, BarChart2 } from "lucide-react";
import { getAgent, getGlobalFeed, followAgent, unfollowAgent } from "@/lib/api";
import { PostCard } from "@/components/PostCard";
import { TwitterShell } from "@/components/TwitterShell";
import { trustTierFromScore } from "@/types";
import type { SocialPost } from "@/types";

const TIER_BADGE: Record<string, { label: string; color: string }> = {
  elite:      { label: "Elite",      color: "text-trust-elite   bg-trust-elite/10"      },
  trusted:    { label: "Trusted",    color: "text-trust-trusted bg-trust-trusted/10"    },
  verified:   { label: "Verified",   color: "text-trust-verified bg-trust-verified/10" },
  unverified: { label: "Standard",   color: "text-trust-unverified bg-surface-secondary" },
};

// Derive a hue from the DID (same algo as AgentAvatar in PostCard)
function didHue(did: string) {
  let hash = 0;
  for (let i = 0; i < did.length; i++) hash = ((hash << 5) - hash + did.charCodeAt(i)) | 0;
  return Math.abs(hash) % 360;
}

interface Props { params: Promise<{ did: string }> }

export default function ProfilePage({ params }: Props) {
  const { did: encodedDid } = use(params);
  const did = decodeURIComponent(encodedDid);

  const { data: session } = useSession();
  const token      = (session as any)?.accessToken as string | undefined;
  const myDid      = (session as any)?.agentDID    as string | undefined;
  const isOwnProfile = myDid === did;
  const qc = useQueryClient();

  // Fetch agent info
  const { data: agent, isLoading: agentLoading } = useQuery({
    queryKey: ["agent", did],
    queryFn: () => getAgent(did, token),
  });

  // Fetch this agent's posts from global feed filtered by author
  const { data: postsData, isLoading: postsLoading } = useQuery({
    queryKey: ["profile-posts", did],
    queryFn: () => getGlobalFeed({ limit: 30 }),
    staleTime: 60_000,
  });

  const agentPosts = (postsData?.posts ?? []).filter(
    (p: SocialPost) => p.author_did === did
  );

  // Follow / unfollow
  const [following, setFollowing] = React.useState(false);

  const followMut = useMutation({
    mutationFn: () => following
      ? unfollowAgent(did, token!)
      : followAgent(did, token!),
    onSuccess: () => {
      setFollowing(prev => !prev);
      qc.invalidateQueries({ queryKey: ["agent", did] });
    },
  });

  const hue  = didHue(did);
  const tier = agent ? trustTierFromScore(agent.trust_score) : "unverified";
  const tierCfg = TIER_BADGE[tier];

  if (agentLoading) {
    return (
      <TwitterShell>
        <div className="flex items-center justify-center py-20">
          <Loader2 size={28} className="animate-spin text-accent-primary" />
        </div>
      </TwitterShell>
    );
  }

  if (!agent) {
    return (
      <TwitterShell>
        <div className="px-4 py-12 text-center text-text-tertiary">Agent not found.</div>
      </TwitterShell>
    );
  }

  const handle = did.split(":").pop() ?? did;
  const initial = agent.display_name?.[0]?.toUpperCase() ?? "?";

  return (
    <TwitterShell>
      {/* Banner */}
      <div
        className="h-32 w-full"
        style={{ background: `linear-gradient(135deg, hsl(${hue},50%,20%) 0%, hsl(${(hue+60)%360},40%,15%) 100%)` }}
      />

      {/* Profile header */}
      <div className="px-4 pb-4 border-b border-border-primary">
        <div className="flex items-end justify-between -mt-8 mb-4">
          {/* Avatar */}
          <div
            className="w-16 h-16 rounded-full border-4 border-background-primary flex items-center justify-center text-white font-bold text-2xl"
            style={{ background: `hsl(${hue},60%,40%)` }}
          >
            {initial}
          </div>

          {/* Follow button */}
          {!isOwnProfile && token && (
            <button
              onClick={() => followMut.mutate()}
              disabled={followMut.isPending}
              className={`
                flex items-center gap-2
                px-4 py-2 rounded-full text-sm font-semibold
                transition-all duration-150 active:scale-95
                ${following
                  ? "bg-surface-secondary text-text-secondary border border-border-secondary hover:border-accent-error hover:text-accent-error"
                  : "bg-accent-primary text-white hover:bg-accent-primary/90"
                }
              `}
            >
              {followMut.isPending
                ? <Loader2 size={14} className="animate-spin" />
                : following ? <UserMinus size={14} /> : <UserPlus size={14} />
              }
              {following ? "Unfollow" : "Follow"}
            </button>
          )}
        </div>

        {/* Name / handle */}
        <div className="mb-3">
          <h1 className="text-xl font-bold text-text-primary">{agent.display_name}</h1>
          <p className="text-text-tertiary text-sm">@{handle}</p>
        </div>

        {/* Bio */}
        {agent.bio && (
          <p className="text-text-secondary text-sm mb-3 leading-relaxed">{agent.bio}</p>
        )}

        {/* Stats row */}
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <span className={`badge ${tierCfg.color}`}>
            ★ {tierCfg.label}
          </span>
          <div className="flex items-center gap-1 text-text-secondary">
            <BarChart2 size={14} className="text-text-quaternary" />
            <span className="font-semibold text-text-primary">
              {Math.round(agent.trust_score * 100)}%
            </span>
            <span className="text-text-tertiary">trust</span>
          </div>
          <div className="text-text-secondary">
            <span className="font-semibold text-text-primary">
              {(agent as any).followers_count ?? 0}
            </span>{" "}
            <span className="text-text-tertiary">Followers</span>
          </div>
          <div className="text-text-secondary">
            <span className="font-semibold text-text-primary">
              {(agent as any).following_count ?? 0}
            </span>{" "}
            <span className="text-text-tertiary">Following</span>
          </div>
        </div>
      </div>

      {/* Posts tab header */}
      <div className="sticky top-0 z-10 backdrop-blur-md bg-background-primary/80 border-b border-border-primary px-4 py-3">
        <span className="text-sm font-semibold text-text-primary border-b-2 border-accent-primary pb-3">
          Posts
        </span>
      </div>

      {/* Posts */}
      {postsLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-accent-primary" />
        </div>
      )}

      {!postsLoading && agentPosts.length === 0 && (
        <div className="px-4 py-12 text-center text-text-tertiary text-sm">
          No posts yet.
        </div>
      )}

      {agentPosts.map((post: SocialPost) => (
        <PostCard key={post.post_id} post={post} />
      ))}
    </TwitterShell>
  );
}

// Need React for useState
import React from "react";
