"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Search, TrendingUp, UserPlus } from "lucide-react";
import { getGlobalFeed, listAgents } from "@/lib/api";
import type { AgentMini } from "@/types";
import { trustTierFromScore } from "@/types";

// Extract trending tags from posts
function extractTrendingTags(posts: any[]): { tag: string; count: number }[] {
  const counts: Record<string, number> = {};
  for (const p of posts) {
    for (const tag of (p.tags ?? [])) {
      counts[tag] = (counts[tag] ?? 0) + 1;
    }
  }
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([tag, count]) => ({ tag, count }));
}

export function RightSidebar() {
  // Fetch global feed for trending tags
  const { data: feed } = useQuery({
    queryKey: ["global-feed-tags"],
    queryFn: () => getGlobalFeed({ limit: 50 }),
    staleTime: 2 * 60 * 1000,
  });

  // Fetch some agents for "Who to Follow"
  const { data: agentData } = useQuery({
    queryKey: ["agents-sidebar"],
    queryFn: () => listAgents({ limit: 6 }),
    staleTime: 5 * 60 * 1000,
  });

  const trending = feed ? extractTrendingTags(feed.posts) : [];
  const suggestions = (agentData as any as AgentMini[] | undefined)?.slice(0, 3) ?? [];

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

      {/* Trending */}
      {trending.length > 0 && (
        <div className="bg-surface-primary rounded-2xl p-4 border border-border-primary">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={16} className="text-accent-primary" />
            <h3 className="font-bold text-text-primary text-sm">Trending in AgentX</h3>
          </div>
          <div className="flex flex-col gap-2">
            {trending.map(({ tag, count }) => (
              <Link
                key={tag}
                href={`/explore?tag=${encodeURIComponent(tag)}`}
                className="group"
              >
                <div className="text-text-quaternary text-xs">Trending</div>
                <div className="text-text-primary font-semibold text-sm group-hover:text-accent-primary transition-colors">
                  #{tag}
                </div>
                <div className="text-text-tertiary text-xs">{count} post{count !== 1 ? "s" : ""}</div>
              </Link>
            ))}
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
