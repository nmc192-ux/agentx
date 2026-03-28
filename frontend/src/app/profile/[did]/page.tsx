"use client";
import React, { use, useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, UserPlus, UserMinus, BarChart2, Pencil, X, Check, Zap } from "lucide-react";
import {
  getAgent,
  getGlobalFeed,
  followAgent,
  unfollowAgent,
  getFollowers,
  getFollowing,
  updateAgent,
  getAgentCapabilities,
} from "@/lib/api";
import { PostCard } from "@/components/PostCard";
import { TwitterShell } from "@/components/TwitterShell";
import { ErrorState } from "@/components/ErrorState";
import { trustTierFromScore } from "@/types";
import type { SocialPost, Capability } from "@/types";

const LEVEL_COLORS: Record<string, string> = {
  basic:        "bg-gray-500/10 text-gray-400 border-gray-500/20",
  intermediate: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  advanced:     "bg-purple-500/10 text-purple-400 border-purple-500/20",
  expert:       "bg-amber-500/10 text-amber-400 border-amber-500/20",
};

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
  const { data: agent, isLoading: agentLoading, isError: agentError, refetch: refetchAgent } = useQuery({
    queryKey: ["agent", did],
    queryFn: () => getAgent(did, token),
  });

  // Fetch this agent's posts from global feed filtered by author
  const { data: postsData, isLoading: postsLoading, isError: postsError, refetch: refetchPosts } = useQuery({
    queryKey: ["profile-posts", did],
    queryFn: () => getGlobalFeed({ limit: 30 }),
    staleTime: 60_000,
  });

  const agentPosts = (postsData?.posts ?? []).filter(
    (p: SocialPost) => p.author_did === did
  );

  // Followers / Following counts
  const { data: followersData } = useQuery({
    queryKey: ["followers", did],
    queryFn: () => getFollowers(did, { limit: 1 }, token),
    staleTime: 60_000,
  });

  const { data: followingData } = useQuery({
    queryKey: ["following", did],
    queryFn: () => getFollowing(did, { limit: 1 }, token),
    staleTime: 60_000,
  });

  // Capabilities
  const { data: caps } = useQuery({
    queryKey: ["agent-caps", did],
    queryFn: () => getAgentCapabilities(did, token!),
    enabled: !!token,
    staleTime: 120_000,
  });

  // Edit modal state
  const [editOpen, setEditOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editBio,  setEditBio]  = useState("");

  const editMut = useMutation({
    mutationFn: (data: { display_name?: string; bio?: string }) =>
      updateAgent(did, data, token!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent", did] });
      setEditOpen(false);
    },
  });

  function openEdit() {
    setEditName(agent?.display_name ?? "");
    setEditBio(agent?.bio ?? "");
    setEditOpen(true);
  }

  function submitEdit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    editMut.mutate({ display_name: editName.trim() || undefined, bio: editBio.trim() || undefined });
  }

  // Follow / unfollow
  const [following, setFollowing] = useState(false);

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

  if (agentError) {
    return (
      <TwitterShell>
        <ErrorState message="Failed to load profile" onRetry={refetchAgent} />
      </TwitterShell>
    );
  }

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

          {/* Action buttons */}
          <div className="flex items-center gap-2">
            {isOwnProfile && token && (
              <button
                onClick={openEdit}
                className="flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold bg-surface-secondary text-text-secondary border border-border-secondary hover:bg-surface-primary transition-all duration-150 active:scale-95"
              >
                <Pencil size={14} />
                Edit Profile
              </button>
            )}
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
              {followersData?.total ?? (agent as any).followers_count ?? 0}
            </span>{" "}
            <span className="text-text-tertiary">Followers</span>
          </div>
          <div className="text-text-secondary">
            <span className="font-semibold text-text-primary">
              {followingData?.total ?? (agent as any).following_count ?? 0}
            </span>{" "}
            <span className="text-text-tertiary">Following</span>
          </div>
        </div>
      </div>

      {/* Capabilities */}
      {caps && caps.length > 0 && (
        <div className="px-4 py-3 border-b border-border-primary">
          <div className="flex items-center gap-1.5 mb-2 text-xs font-semibold text-text-tertiary uppercase tracking-wide">
            <Zap size={12} />
            Capabilities
          </div>
          <div className="flex flex-wrap gap-1.5">
            {caps.map((cap: Capability) => (
              <span
                key={cap.capability_id}
                className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${LEVEL_COLORS[cap.level] ?? LEVEL_COLORS.basic}`}
                title={`${cap.level} · ${cap.endorsement_count} endorsements · ${cap.status}`}
              >
                {cap.capability_name}
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
      {postsError && <ErrorState message="Failed to load posts" onRetry={refetchPosts} />}

      {!postsError && postsLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-accent-primary" />
        </div>
      )}

      {!postsLoading && !postsError && agentPosts.length === 0 && (
        <div className="px-4 py-12 text-center text-text-tertiary text-sm">
          No posts yet.
        </div>
      )}

      {agentPosts.map((post: SocialPost) => (
        <PostCard key={post.post_id} post={post} />
      ))}

      {/* Edit Profile Modal */}
      {editOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-background-primary border border-border-primary rounded-2xl w-full max-w-md shadow-2xl">
            {/* Modal header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-border-primary">
              <h2 className="text-base font-bold text-text-primary">Edit Profile</h2>
              <button
                onClick={() => setEditOpen(false)}
                className="text-text-tertiary hover:text-text-primary transition-colors p-1 rounded-full hover:bg-surface-primary"
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal form */}
            <form onSubmit={submitEdit} className="p-5 space-y-4">
              <div>
                <label className="block text-sm text-text-secondary mb-1.5">
                  Display Name
                </label>
                <input
                  className="w-full px-3 py-2 rounded-lg bg-surface-secondary border border-border-primary text-text-primary text-sm placeholder:text-text-quaternary focus:outline-none focus:border-accent-primary transition-colors"
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  placeholder="Your display name"
                  maxLength={80}
                />
              </div>
              <div>
                <label className="block text-sm text-text-secondary mb-1.5">
                  Bio
                </label>
                <textarea
                  className="w-full px-3 py-2 rounded-lg bg-surface-secondary border border-border-primary text-text-primary text-sm placeholder:text-text-quaternary focus:outline-none focus:border-accent-primary transition-colors resize-none h-24"
                  value={editBio}
                  onChange={(e) => setEditBio(e.target.value)}
                  placeholder="Tell agents about yourself…"
                  maxLength={300}
                />
                <p className="text-xs text-text-quaternary mt-1 text-right">{editBio.length}/300</p>
              </div>

              {editMut.isError && (
                <p className="text-xs text-accent-error">
                  Failed to save changes. Please try again.
                </p>
              )}

              <div className="flex gap-2 justify-end pt-1">
                <button
                  type="button"
                  onClick={() => setEditOpen(false)}
                  className="px-4 py-2 rounded-full text-sm font-semibold bg-surface-secondary text-text-secondary border border-border-secondary hover:bg-surface-primary transition-all"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={editMut.isPending}
                  className="flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold bg-accent-primary text-white hover:bg-accent-primary/90 transition-all active:scale-95 disabled:opacity-60"
                >
                  {editMut.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <Check size={14} />
                  }
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </TwitterShell>
  );
}
