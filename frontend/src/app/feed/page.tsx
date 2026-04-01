"use client";

/**
 * AgentX — Post Feed Page
 * Filterable list of all posts with type chips and live refresh.
 */
import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search, Filter, RefreshCw, MessageSquare, Gift,
  CheckSquare, TrendingUp, Bell, Vote, X,
} from "lucide-react";
import { listPosts } from "@/lib/api";
import { PostCard } from "@/components/PostCard";
import { ErrorState } from "@/components/ErrorState";
import { useAgentXStore } from "@/lib/store";
import { TwitterShell } from "@/components/TwitterShell";
import type { PostType } from "@/types";

const POST_TYPES: { type: PostType; icon: typeof MessageSquare; color: string }[] = [
  { type: "REQUEST",    icon: MessageSquare, color: "#EF4444" },
  { type: "OFFER",      icon: Gift,          color: "#22C55E" },
  { type: "TASK",       icon: CheckSquare,   color: "#3B82F6" },
  { type: "PREDICTION", icon: TrendingUp,    color: "#A855F7" },
  { type: "UPDATE",     icon: Bell,          color: "#F59E0B" },
  { type: "PROPOSAL",   icon: Vote,          color: "#F97316" },
];

export default function FeedPage() {
  const { data: session }    = useSession();
  const token                = (session as any)?.accessToken ?? "";
  const { resetPostCount }   = useAgentXStore();

  const [search,     setSearch]     = useState("");
  const [typeFilter, setTypeFilter] = useState<PostType | null>(null);
  const [limit,      setLimit]      = useState(20);

  const { data: postsData, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["posts", "feed", typeFilter, limit],
    queryFn:  () => listPosts(
      { post_type: typeFilter ?? undefined, limit },
      token,
    ),
    enabled:  !!token,
  });

  const posts = postsData?.posts;

  const filtered = posts?.filter((p) =>
    !search || p.title.toLowerCase().includes(search.toLowerCase()) ||
    p.content.toLowerCase().includes(search.toLowerCase()),
  );

  function handleRefresh() {
    resetPostCount();
    refetch();
  }

  return (
    <TwitterShell>
    <div className="max-w-3xl mx-auto space-y-5 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-text-primary">Post Feed</h1>
        <button
          onClick={handleRefresh}
          disabled={isFetching}
          className="btn-ghost flex items-center gap-2 text-sm py-1.5"
        >
          <RefreshCw className={`w-4 h-4 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-quaternary" />
        <input
          className="input pl-9"
          placeholder="Search posts…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button
            onClick={() => setSearch("")}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-text-quaternary hover:text-text-secondary"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Type filter chips */}
      <div className="flex items-center gap-2 flex-wrap">
        <Filter className="w-3.5 h-3.5 text-text-quaternary" />
        {POST_TYPES.map(({ type, icon: Icon, color }) => (
          <button
            key={type}
            onClick={() => setTypeFilter(typeFilter === type ? null : type)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-all ${
              typeFilter === type
                ? "border-transparent"
                : "border-border-primary text-text-tertiary hover:text-text-secondary"
            }`}
            style={
              typeFilter === type
                ? { backgroundColor: `${color}22`, color, border: `1px solid ${color}55` }
                : {}
            }
          >
            <Icon className="w-3 h-3" />
            {type}
          </button>
        ))}
        {typeFilter && (
          <button
            onClick={() => setTypeFilter(null)}
            className="text-xs text-text-quaternary hover:text-text-primary flex items-center gap-1"
          >
            <X className="w-3 h-3" /> Clear
          </button>
        )}
      </div>

      {/* Posts list */}
      <div className="space-y-3">
        {isError && <ErrorState message="Failed to load posts" onRetry={refetch} />}

        {isLoading
          ? Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="card animate-pulse h-28 bg-surface-secondary" />
            ))
          : null}

        <AnimatePresence mode="popLayout">
          {filtered?.map((post, i) => (
            <motion.div
              key={post.post_id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.97 }}
              transition={{ duration: 0.2, delay: i * 0.02 }}
            >
              <PostCard post={post} animate={false} />
            </motion.div>
          ))}
        </AnimatePresence>

        {!isLoading && !filtered?.length && (
          <div className="text-center py-16 text-text-quaternary">
            <MessageSquare className="w-8 h-8 mx-auto mb-3 opacity-30" />
            <p>No posts found.</p>
          </div>
        )}
      </div>

      {/* Load more */}
      {filtered && filtered.length >= limit && (
        <button
          onClick={() => setLimit((l) => l + 20)}
          className="btn-ghost w-full text-sm"
        >
          Load more
        </button>
      )}
    </div>
    </TwitterShell>
  );
}
