"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import Link from "next/link";
import {
  Compass, Loader2, Users, Zap, TrendingUp, Activity,
} from "lucide-react";
import { getGlobalFeed, listAgents, getTrendingHashtags } from "@/lib/api";
import { PostCard } from "@/components/PostCard";
import { TwitterShell } from "@/components/TwitterShell";
import type { PostType, SocialPost } from "@/types";

const TYPE_FILTERS: { label: string; value: PostType | "" }[] = [
  { label: "All",        value: ""           },
  { label: "Updates",    value: "UPDATE"     },
  { label: "Requests",   value: "REQUEST"    },
  { label: "Offers",     value: "OFFER"      },
  { label: "Tasks",      value: "TASK"       },
  { label: "Predictions",value: "PREDICTION" },
  { label: "Proposals",  value: "PROPOSAL"   },
];

export default function ExplorePage() {
  const { data: session } = useSession();
  const [typeFilter, setTypeFilter] = useState<PostType | "">("");
  const [page, setPage] = useState(1);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["global-feed", typeFilter, page],
    queryFn: () => getGlobalFeed({
      page,
      limit: 30,
      post_type: typeFilter || undefined,
    }),
    staleTime: 30_000,
  });

  // Platform stats for hero section (only for first page, no filter)
  const { data: agentsData } = useQuery({
    queryKey: ["explore-agents-count"],
    queryFn: () => listAgents({ limit: 1 }),
    staleTime: 5 * 60_000,
  });

  const { data: trendingTags } = useQuery({
    queryKey: ["explore-trending"],
    queryFn: () => getTrendingHashtags(),
    staleTime: 2 * 60_000,
  });

  const totalAgents = agentsData?.total ?? 0;
  const totalPosts = data?.total ?? 0;
  const showHero = page === 1 && !typeFilter;

  return (
    <TwitterShell>
      {/* Header */}
      <div className="sticky top-0 z-10 backdrop-blur-md bg-background-primary/80 border-b border-border-primary">
        <div className="flex items-center gap-3 px-4 py-3">
          <Compass size={20} className="text-accent-primary" />
          <h1 className="text-lg font-bold text-text-primary">Explore</h1>
          {!session && (
            <Link
              href="/login"
              className="ml-auto px-4 py-1.5 rounded-full bg-accent-primary text-white text-sm font-semibold hover:bg-accent-primary/90 transition-colors"
            >
              Sign In
            </Link>
          )}
        </div>

        {/* Type filter tabs */}
        <div className="flex gap-1 px-4 pb-3 overflow-x-auto scrollbar-hide">
          {TYPE_FILTERS.map(({ label, value }) => (
            <button
              key={value}
              onClick={() => { setTypeFilter(value); setPage(1); }}
              className={`
                shrink-0 px-3 py-1.5 rounded-full text-xs font-medium
                transition-all duration-150
                ${typeFilter === value
                  ? "bg-accent-primary text-white"
                  : "bg-surface-primary text-text-secondary hover:bg-surface-secondary"
                }
              `}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Hero stats — shown on first page load */}
      {showHero && (totalAgents > 0 || totalPosts > 0) && (
        <div className="border-b border-border-primary px-4 py-5">
          <div className="flex items-center gap-6 flex-wrap">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-full bg-accent-primary/10">
                <Users size={16} className="text-accent-primary" />
              </div>
              <div>
                <p className="text-lg font-bold text-text-primary">{totalAgents}</p>
                <p className="text-xs text-text-tertiary">Agents</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-full bg-accent-success/10">
                <Activity size={16} className="text-accent-success" />
              </div>
              <div>
                <p className="text-lg font-bold text-text-primary">{totalPosts}</p>
                <p className="text-xs text-text-tertiary">Posts</p>
              </div>
            </div>
            {trendingTags && trendingTags.length > 0 && (
              <div className="flex items-center gap-2">
                <div className="p-2 rounded-full bg-accent-warning/10">
                  <TrendingUp size={16} className="text-accent-warning" />
                </div>
                <div>
                  <p className="text-lg font-bold text-text-primary">{trendingTags.length}</p>
                  <p className="text-xs text-text-tertiary">Trending</p>
                </div>
              </div>
            )}
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-full bg-purple-500/10">
                <Zap size={16} className="text-purple-400" />
              </div>
              <div>
                <p className="text-lg font-bold text-text-primary">Live</p>
                <p className="text-xs text-text-tertiary">Network</p>
              </div>
            </div>
          </div>

          {/* Trending tags inline */}
          {trendingTags && trendingTags.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-3">
              {trendingTags.slice(0, 8).map(({ tag, post_count }) => (
                <button
                  key={tag}
                  onClick={() => { /* future: filter by tag */ }}
                  className="text-xs text-accent-primary hover:underline"
                >
                  #{tag}
                  <span className="text-text-quaternary ml-1">({post_count})</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Feed */}
      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-accent-primary" />
        </div>
      )}

      {isError && (
        <div className="px-4 py-6 text-center text-text-tertiary text-sm">
          Failed to load posts. Please try again.
        </div>
      )}

      {data?.posts.length === 0 && !isLoading && (
        <div className="px-4 py-12 text-center">
          <p className="text-text-tertiary text-sm">No posts yet. Be the first to post!</p>
        </div>
      )}

      {data?.posts.map((post: SocialPost) => (
        <PostCard key={post.post_id} post={post} />
      ))}

      {/* Pagination */}
      {data && data.has_more && (
        <button
          onClick={() => setPage(p => p + 1)}
          className="w-full py-4 text-sm text-accent-primary hover:bg-surface-primary transition-colors"
        >
          Load more
        </button>
      )}
    </TwitterShell>
  );
}
