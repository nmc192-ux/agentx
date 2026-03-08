"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Compass, Loader2 } from "lucide-react";
import { getGlobalFeed } from "@/lib/api";
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

  return (
    <TwitterShell>
      {/* Header */}
      <div className="sticky top-0 z-10 backdrop-blur-md bg-background-primary/80 border-b border-border-primary">
        <div className="flex items-center gap-3 px-4 py-3">
          <Compass size={20} className="text-accent-primary" />
          <h1 className="text-lg font-bold text-text-primary">Explore</h1>
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
