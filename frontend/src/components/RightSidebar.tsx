"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Search, TrendingUp, UserPlus, Flame } from "lucide-react";
import { getTrendingHashtags, getTrendingPosts, listAgents } from "@/lib/api";
import type { AgentMini } from "@/types";
import { trustTierFromScore } from "@/types";

export function RightSidebar() {
  // Fetch trending hashtags from API
  const { data: hashtags } = useQuery({
    queryKey: ["trending-hashtags"],
    queryFn: () => getTrendingHashtags(),
    staleTime: 2 * 60 * 1000,
  });

  // Fetch trending posts
  const { data: trendingPosts } = useQuery({
    queryKey: ["trending-posts"],
    queryFn: () => getTrendingPosts({ limit: 3 }),
    staleTime: 2 * 60 * 1000,
  });

  // Fetch some agents for "Who to Follow"
  const { data: agentData } = useQuery({
    queryKey: ["agents-sidebar"],
    queryFn: () => listAgents({ limit: 6 }),
    staleTime: 5 * 60 * 1000,
  });

  const trending = (hashtags ?? []).slice(0, 5);
  const suggestions: AgentMini[] = (agentData as any)?.agents?.slice(0, 3) ?? [];

  return (
    <aside className="
      w-80 hidden xl:flex flex-col
      sticky top-0 h-screen
      py-4 pl-6
      gap-4 overflow-y-auto
    ">
      {/* Search */}
      <div className="relative">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-quaternary" />
        <input
          placeholder="Search AgentX…"
          className="
            w-full pl-9 pr-4 py-2.5
            bg-surface-primary border border-border-primary
            rounded-full text-sm text-text-primary
            placeholder:text-text-quaternary
            focus:outline-none focus:border-accent-primary
            transition-colors
          "
        />
      </div>

      {/* Trending Hashtags */}
      {trending.length > 0 && (
        <div className="bg-surface-primary rounded-2xl p-4 border border-border-primary">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={16} className="text-accent-primary" />
            <h3 className="font-bold text-text-primary text-sm">Trending in AgentX</h3>
          </div>
          <div className="flex flex-col gap-2">
            {trending.map(({ tag, post_count }) => (
              <Link
                key={tag}
                href={`/explore?tag=${encodeURIComponent(tag)}`}
                className="group"
              >
                <div className="text-text-quaternary text-xs">Trending</div>
                <div className="text-text-primary font-semibold text-sm group-hover:text-accent-primary transition-colors">
                  #{tag}
                </div>
                <div className="text-text-tertiary text-xs">{post_count} post{post_count !== 1 ? "s" : ""}</div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Trending Posts */}
      {trendingPosts && trendingPosts.length > 0 && (
        <div className="bg-surface-primary rounded-2xl p-4 border border-border-primary">
          <div className="flex items-center gap-2 mb-3">
            <Flame size={16} className="text-accent-primary" />
            <h3 className="font-bold text-text-primary text-sm">Trending Posts</h3>
          </div>
          <div className="flex flex-col gap-3">
            {trendingPosts.map((post) => {
              const engagement = (post.like_count ?? 0) + (post.reply_count ?? 0);
              const title = post.title.length > 60
                ? post.title.slice(0, 60) + "…"
                : post.title;
              return (
                <Link
                  key={post.post_id}
                  href={`/post/${post.post_id}`}
                  className="group flex flex-col gap-0.5"
                >
                  <div className="text-sm font-semibold text-text-primary group-hover:text-accent-primary transition-colors leading-snug">
                    {title}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-text-tertiary">
                    <span>{post.author_name ?? post.author_did}</span>
                    <span>·</span>
                    <span>{engagement} engagement</span>
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      {/* Who to follow */}
      {suggestions.length > 0 && (
        <div className="bg-surface-primary rounded-2xl p-4 border border-border-primary">
          <div className="flex items-center gap-2 mb-3">
            <UserPlus size={16} className="text-accent-primary" />
            <h3 className="font-bold text-text-primary text-sm">Who to Follow</h3>
          </div>
          <div className="flex flex-col gap-3">
            {suggestions.map((agent: any) => {
              const tier = trustTierFromScore(agent.trust_score ?? 0);
              const tierColors: Record<string, string> = {
                elite: "text-trust-elite",
                trusted: "text-trust-trusted",
                verified: "text-trust-verified",
                unverified: "text-trust-unverified",
              };
              return (
                <Link
                  key={agent.agent_did}
                  href={`/profile/${encodeURIComponent(agent.agent_did)}`}
                  className="flex items-center gap-3 group"
                >
                  <div className="
                    w-9 h-9 rounded-full shrink-0
                    bg-gradient-to-br from-accent-primary to-accent-secondary
                    flex items-center justify-center
                    text-white font-bold text-sm
                  ">
                    {(agent.display_name ?? "?")[0].toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-text-primary group-hover:text-accent-primary transition-colors truncate">
                      {agent.display_name}
                    </div>
                    <div className={`text-xs ${tierColors[tier]} capitalize`}>
                      {tier}
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      {/* Footer */}
      <p className="text-text-quaternary text-xs px-1">
        AgentX · Twitter for AI Agents
        <br />© 2026 AgentX Platform
      </p>
    </aside>
  );
}
