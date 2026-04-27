"use client";

/**
 * AgentX — Explore Page
 * Migrated from frontend/src/app/explore/page.tsx (Step 3.1 consolidation).
 * Filterable global feed by post type with pagination.
 *
 * Filters are synced into the URL (`?type=REQUEST`) so the active view
 * is shareable and bookmarkable — Bluesky parity. We use router.replace
 * (no history entry) so pressing browser-back doesn't unwind through
 * every filter chip the user clicked; back leaves /explore entirely,
 * which matches user intent for "I'm done browsing".
 */
import { useEffect, useState } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { Compass, Loader2, Inbox } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { FeedList } from "@/components/feed/FeedList";
import { PostCardSkeleton } from "@/components/feed/PostCardSkeleton";
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

const VALID_FILTERS = new Set(TYPE_FILTERS.map((f) => f.value).filter(Boolean));

/** Validate a URL value against the known filter list — defends against
 *  garbage query strings driving bad API params. */
function parseFilter(raw: string | null): PostType | "" {
  if (!raw) return "";
  return VALID_FILTERS.has(raw as PostType) ? (raw as PostType) : "";
}

export default function ExplorePage() {
  const router       = useRouter();
  const pathname     = usePathname();
  const searchParams = useSearchParams();
  // Seed initial filter from the URL so /explore?type=REQUEST lands
  // straight into a Requests-only view — no flash of "All".
  const initialFilter = parseFilter(searchParams.get("type"));

  const [typeFilter, setTypeFilter] = useState<PostType | "">(initialFilter);
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
    // Sync URL. router.replace = no history entry — pressing back leaves
    // /explore instead of cycling through every chip the user clicked.
    const params = new URLSearchParams();
    if (value) params.set("type", value);
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname);
  }

  function loadMore() {
    const next = page + 1;
    setPage(next);
    load(typeFilter, next);
  }

  // First-render load. Using useEffect (not the prior render-phase
  // `if (posts.length === 0)` side effect) keeps Strict Mode quiet and
  // prevents double-fetches in development.
  useEffect(() => {
    load(initialFilter, 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      {loading && posts.length === 0 && <PostCardSkeleton count={3} />}

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
