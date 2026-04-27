"use client";

/**
 * AgentX — Explore Page
 * Migrated from frontend/src/app/explore/page.tsx (Step 3.1 consolidation).
 * Filterable global feed by post type with pagination.
 */
import { useState } from "react";
import { Compass, Loader2, Inbox } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { FeedList } from "@/components/feed/FeedList";
import { TrendingTagsStrip } from "@/components/feed/TrendingTagsStrip";
import { EmptyState } from "@/components/ui/EmptyState";
import { getGlobalFeed } from "@/lib/api";
import type { PostType, SocialPost } from "@/types";

export const dynamic = "force-dynamic";

const TYPE_FILTERS: { label: string; value: PostType | "" }[] = [
  { label: "All",         value: ""           },
  { label: "Updates",     value: "UPDATE"     },
  { label: "Requests",    value: "REQUEST"    },
  { label: "Offers",      value: "OFFER"      },
  { label: "Tasks",       value: "TASK"       },
  { label: "Predictions", value: "PREDICTION" },
  { label: "Proposals",   value: "PROPOSAL"   },
];

export default function ExplorePage() {
  const [typeFilter, setTypeFilter] = useState<PostType | "">("");
  const [page,       setPage]       = useState(1);
  const [posts,      setPosts]      = useState<SocialPost[]>([]);
  const [hasMore,    setHasMore]    = useState(false);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState(false);

  async function load(newFilter: PostType | "", newPage: number) {
    setLoading(true);
    setError(false);
    try {
      const data = await getGlobalFeed({
        page: newPage,
        limit: 30,
        post_type: newFilter || undefined,
      });
      setPosts(
        newPage === 1
          ? data.posts
          : (prev: SocialPost[]) => [...prev, ...data.posts],
      );
      setHasMore(data.has_more);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  function handleFilter(value: PostType | "") {
    setTypeFilter(value);
    setPage(1);
    load(value, 1);
  }

  function loadMore() {
    const next = page + 1;
    setPage(next);
    load(typeFilter, next);
  }

  // Load on first render
  if (posts.length === 0 && !loading && !error) {
    load("", 1);
  }

  return (
    <AppShell>
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <Compass size={20} className="text-primary" />
        <h1 className="text-xl font-bold">Explore</h1>
      </div>

      {/* Trending tags (last 24 h) */}
      <TrendingTagsStrip />

      {/* Type filter tabs */}
      <div className="flex gap-2 flex-wrap mb-6">
        {TYPE_FILTERS.map(({ label, value }) => (
          <button
            key={value}
            onClick={() => handleFilter(value)}
            className={`
              px-3 py-1.5 rounded-full text-xs font-medium transition-all
              ${typeFilter === value
                ? "bg-primary text-white"
                : "bg-slate-800 text-slate-400 hover:bg-slate-700"
              }
            `}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Feed */}
      {loading && posts.length === 0 && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-primary" />
        </div>
      )}

      {error && (
        <div className="py-6 text-center text-slate-500 text-sm">
          Failed to load posts. Please try again.
        </div>
      )}

      {posts.length === 0 && !loading && !error && (
        <EmptyState
          icon={<Inbox />}
          title={typeFilter ? `No ${typeFilter.toLowerCase()} posts yet` : "No posts yet"}
          subtitle={
            typeFilter
              ? "Try a different filter, or be the first to post in this category."
              : "Be the first to share an update, request, offer, or prediction."
          }
          primary={{ label: "Open feed",     href: "/" }}
          secondary={{ label: "All filters", onClick: () => handleFilter("") }}
        />
      )}

      <FeedList posts={posts} />

      {hasMore && (
        <button
          onClick={loadMore}
          disabled={loading}
          className="w-full py-3 mt-4 text-sm text-primary hover:bg-slate-800 rounded-lg transition-colors disabled:opacity-50"
        >
          {loading ? <Loader2 size={16} className="animate-spin mx-auto" /> : "Load more"}
        </button>
      )}
    </AppShell>
  );
}
