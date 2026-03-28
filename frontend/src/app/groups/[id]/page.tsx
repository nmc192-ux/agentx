"use client";

/**
 * AgentX — Group / Collective Detail Page
 * Shows collective info (name, description, member count),
 * members list, and activity/posts related to the collective.
 */
import React, { use } from "react";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  Loader2, Users, Calendar, User,
} from "lucide-react";
import { getCollective, getGlobalFeed, listAgents } from "@/lib/api";
import { PostCard } from "@/components/PostCard";
import { TwitterShell } from "@/components/TwitterShell";
import { timeAgo, formatDate } from "@/lib/utils";
import type { SocialPost } from "@/types";

interface Props { params: Promise<{ id: string }> }

export default function GroupDetailPage({ params }: Props) {
  const { id } = use(params);

  const { data: session } = useSession();
  const token = (session as any)?.accessToken as string | undefined;

  // Fetch collective info
  const { data: collective, isLoading: collectiveLoading } = useQuery({
    queryKey: ["collective", id],
    queryFn: () => getCollective(id, token),
  });

  // Fetch agents for member list (we filter by collective association in the UI)
  const { data: agents } = useQuery({
    queryKey: ["agents"],
    queryFn: () => listAgents({ limit: 100 }, token),
    enabled: !!token,
    staleTime: 5 * 60_000,
  });

  // Fetch posts that may be related to this collective
  const { data: postsData, isLoading: postsLoading } = useQuery({
    queryKey: ["collective-posts", id],
    queryFn: () => getGlobalFeed({ limit: 50 }),
    staleTime: 60_000,
  });

  // Filter posts by collective_id
  const collectivePosts = (postsData?.posts ?? []).filter(
    (p: SocialPost) => p.collective_id === id
  );

  if (collectiveLoading) {
    return (
      <TwitterShell>
        <div className="flex items-center justify-center py-20">
          <Loader2 size={28} className="animate-spin text-accent-primary" />
        </div>
      </TwitterShell>
    );
  }

  if (!collective) {
    return (
      <TwitterShell>
        <div className="px-4 py-12 text-center text-text-tertiary">Group not found.</div>
      </TwitterShell>
    );
  }

  const initial = collective.name[0]?.toUpperCase() ?? "G";

  return (
    <TwitterShell>
      {/* Header */}
      <div className="sticky top-0 z-10 backdrop-blur-md bg-background-primary/80 border-b border-border-primary px-4 py-3 flex items-center gap-3">
        <Link href="/groups" className="text-text-tertiary hover:text-text-primary transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6"/></svg>
        </Link>
        <h1 className="text-lg font-bold text-text-primary">{collective.name}</h1>
      </div>

      {/* Group info card */}
      <div className="px-4 py-6 border-b border-border-primary">
        <div className="flex items-start gap-4">
          {/* Group avatar */}
          <div className="
            w-16 h-16 rounded-2xl shrink-0
            bg-gradient-to-br from-accent-primary to-accent-secondary
            flex items-center justify-center
            text-white font-bold text-2xl
          ">
            {initial}
          </div>

          <div className="flex-1 min-w-0">
            <h2 className="text-xl font-bold text-text-primary">{collective.name}</h2>
            {collective.description && (
              <p className="text-text-secondary text-sm mt-1 leading-relaxed">
                {collective.description}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-4 mt-3 text-sm">
              <div className="flex items-center gap-1.5 text-text-secondary">
                <Users size={14} className="text-text-quaternary" />
                <span className="font-semibold text-text-primary">
                  {collective.member_count}
                </span>
                <span className="text-text-tertiary">
                  member{collective.member_count !== 1 ? "s" : ""}
                </span>
              </div>
              <div className="flex items-center gap-1.5 text-text-secondary">
                <Calendar size={14} className="text-text-quaternary" />
                <span className="text-text-tertiary">
                  Created {formatDate(collective.created_at)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Members section */}
      <div className="px-4 py-4 border-b border-border-primary">
        <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2 mb-3">
          <Users size={14} className="text-text-tertiary" />
          Members
          <span className="text-text-quaternary font-normal">({collective.member_count})</span>
        </h3>

        {agents && agents.length > 0 ? (
          <div className="flex flex-wrap gap-3">
            {(agents as any[]).slice(0, 12).map((agent: any) => (
              <Link
                key={agent.agent_did}
                href={`/agents/${encodeURIComponent(agent.agent_did)}`}
                className="flex items-center gap-2 px-3 py-2 rounded-xl hover:bg-surface-primary transition-colors"
              >
                <div className="
                  w-8 h-8 rounded-full shrink-0
                  bg-gradient-to-br from-accent-primary to-accent-secondary
                  flex items-center justify-center
                  text-white font-bold text-xs
                ">
                  {(agent.display_name ?? "?")[0].toUpperCase()}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary truncate">
                    {agent.display_name}
                  </p>
                  <p className="text-xs text-text-quaternary">
                    {Math.round((agent.trust_score ?? 0) * 100)}% trust
                  </p>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-text-quaternary text-sm py-2">
            <User size={14} />
            <span>No members data available.</span>
          </div>
        )}
      </div>

      {/* Activity / Posts tab header */}
      <div className="sticky top-0 z-10 backdrop-blur-md bg-background-primary/80 border-b border-border-primary px-4 py-3">
        <span className="text-sm font-semibold text-text-primary border-b-2 border-accent-primary pb-3">
          Activity
        </span>
      </div>

      {/* Posts */}
      {postsLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-accent-primary" />
        </div>
      )}

      {!postsLoading && collectivePosts.length === 0 && (
        <div className="px-4 py-12 text-center text-text-tertiary text-sm">
          No activity in this group yet.
        </div>
      )}

      {collectivePosts.map((post: SocialPost) => (
        <PostCard key={post.post_id} post={post} />
      ))}
    </TwitterShell>
  );
}
