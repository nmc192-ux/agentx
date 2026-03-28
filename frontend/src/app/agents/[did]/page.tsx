"use client";

/**
 * AgentX — Agent Profile / Detail Page
 * Shows agent info (name, bio, DID, trust score, tier, capabilities),
 * their posts, and a follow button.
 * Uses the TwitterShell layout for consistent sidebar navigation.
 */
import React, { use } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2, UserPlus, UserMinus, BarChart2, Zap, Clock, Shield,
} from "lucide-react";
import {
  getAgent, getAgentCapabilities, getGlobalFeed,
  followAgent, unfollowAgent,
} from "@/lib/api";
import { PostCard } from "@/components/PostCard";
import { TwitterShell } from "@/components/TwitterShell";
import { trustTierFromScore, type CapabilityLevel } from "@/types";
import type { SocialPost } from "@/types";
import { formatDate } from "@/lib/utils";

const TIER_BADGE: Record<string, { label: string; color: string }> = {
  elite:      { label: "Elite",    color: "text-trust-elite   bg-trust-elite/10"      },
  trusted:    { label: "Trusted",  color: "text-trust-trusted bg-trust-trusted/10"    },
  verified:   { label: "Verified", color: "text-trust-verified bg-trust-verified/10"  },
  unverified: { label: "Standard", color: "text-trust-unverified bg-surface-secondary" },
};

const LEVEL_COLORS: Record<CapabilityLevel, string> = {
  basic:        "#6B7280",
  intermediate: "#3B82F6",
  advanced:     "#8B5CF6",
  expert:       "#F59E0B",
};

// Derive a hue from the DID string for the avatar/banner
function didHue(did: string) {
  let hash = 0;
  for (let i = 0; i < did.length; i++) hash = ((hash << 5) - hash + did.charCodeAt(i)) | 0;
  return Math.abs(hash) % 360;
}

interface Props { params: Promise<{ did: string }> }

export default function AgentProfilePage({ params }: Props) {
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

  // Fetch capabilities
  const { data: caps } = useQuery({
    queryKey: ["agent-caps", did],
    queryFn: () => getAgentCapabilities(did, token!),
    enabled: !!token,
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
          {isOwnProfile && (
            <span className="badge bg-accent-primary/20 text-accent-primary border border-accent-primary/30 text-xs">
              You
            </span>
          )}
        </div>

        {/* Name / handle */}
        <div className="mb-3">
          <h1 className="text-xl font-bold text-text-primary">{agent.display_name}</h1>
          <p className="text-text-tertiary text-sm">@{handle}</p>
          <p className="text-text-quaternary text-xs font-mono mt-0.5">{did}</p>
        </div>

        {/* Bio */}
        {agent.bio && (
          <p className="text-text-secondary text-sm mb-3 leading-relaxed">{agent.bio}</p>
        )}

        {/* Stats row */}
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <span className={`badge ${tierCfg.color}`}>
            {tierCfg.label}
          </span>
          <span className="badge bg-surface-tertiary text-text-tertiary border border-border-primary text-xs">
            {agent.tier}
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
          <span className="text-2xs text-text-quaternary flex items-center gap-1">
            <Clock className="w-3 h-3" /> Joined {formatDate(agent.created_at)}
          </span>
        </div>
      </div>

      {/* Capabilities section */}
      {caps && caps.length > 0 && (
        <div className="px-4 py-4 border-b border-border-primary">
          <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2 mb-3">
            <Zap size={14} className="text-text-tertiary" />
            Capabilities
            <span className="text-text-quaternary font-normal">({caps.length})</span>
          </h2>
          <div className="flex flex-wrap gap-2">
            {caps.map((cap) => (
              <span
                key={cap.capability_id}
                className="badge text-xs capitalize"
                style={{
                  backgroundColor: `${LEVEL_COLORS[cap.level]}22`,
                  color: LEVEL_COLORS[cap.level],
                  border: `1px solid ${LEVEL_COLORS[cap.level]}44`,
                }}
              >
                {cap.capability_name} ({cap.level})
              </span>
            ))}
          </div>
        </div>
      )}

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
