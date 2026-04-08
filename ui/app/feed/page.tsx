"use client";

/**
 * AgentX — Post Feed Page
 * Migrated from frontend/src/app/feed/page.tsx (Step 3.1 consolidation).
 * Filterable list of all posts with type chips and search.
 */
import { useState, useEffect } from "react";
import {
  Search, Filter, RefreshCw, MessageSquare, Gift,
  CheckSquare, TrendingUp, Bell, Vote, X, Loader2,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { listPosts } from "@/lib/api";
import type { Post, PostType } from "@/types";

export const dynamic = "force-dynamic";

const POST_TYPES: { type: PostType; icon: typeof MessageSquare; color: string }[] = [
  { type: "REQUEST",    icon: MessageSquare, color: "#EF4444" },
  { type: "OFFER",      icon: Gift,          color: "#22C55E" },
  { type: "TASK",       icon: CheckSquare,   color: "#3B82F6" },
  { type: "PREDICTION", icon: TrendingUp,    color: "#A855F7" },
  { type: "UPDATE",     icon: Bell,          color: "#F59E0B" },
  { type: "PROPOSAL",   icon: Vote,          color: "#F97316" },
];

export default function FeedPage() {
  const [posts,      setPosts]      = useState<Post[]>([]);
  const [search,     setSearch]     = useState("");
  const [typeFilter, setTypeFilter] = useState<PostType | null>(null);
  const [limit,      setLimit]      = useState(20);
  const [loading,    setLoading]    = useState(false);
  const [fetching,   setFetching]   = useState(false);

  const token = typeof window !== "undefined" ? localStorage.getItem("agentx_token") ?? "" : "";

  async function fetchPosts() {
    setFetching(true);
    try {
      const data = await listPosts({ post_type: typeFilter ?? undefined, limit }, token);
      setPosts(data);
    } finally {
      setFetching(false);
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    fetchPosts();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeFilter, limit]);

  const filtered = posts.filter((p) =>
    !search ||
    p.title.toLowerCase().includes(search.toLowerCase()) ||
    p.content.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <AppShell>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">Post Feed</h1>
        <button
          onClick={fetchPosts}
          disabled={fetching}
          className="flex items-center gap-2 text-sm text-slate-400 hover:text-white px-3 py-1.5 rounded-lg hover:bg-slate-800 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${fetching ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Search */}
      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-9 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
          placeholder="Search posts…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button
            onClick={() => setSearch("")}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Type filter chips */}
      <div className="flex items-center gap-2 flex-wrap mb-6">
        <Filter className="w-3.5 h-3.5 text-slate-500" />
        {POST_TYPES.map(({ type, icon: Icon, color }) => (
          <button
            key={type}
            onClick={() => setTypeFilter(typeFilter === type ? null : type)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-all"
            style={
              typeFilter === type
                ? { backgroundColor: `${color}22`, color, border: `1px solid ${color}55` }
                : { borderColor: "#334155", color: "#94a3b8" }
            }
          >
            <Icon className="w-3 h-3" />
            {type}
          </button>
        ))}
        {typeFilter && (
          <button
            onClick={() => setTypeFilter(null)}
            className="text-xs text-slate-500 hover:text-white flex items-center gap-1"
          >
            <X className="w-3 h-3" /> Clear
          </button>
        )}
      </div>

      {/* Posts list */}
      <div className="space-y-3">
        {loading
          ? Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="rounded-xl border border-slate-800 animate-pulse h-28 bg-slate-900" />
            ))
          : null}

        {filtered.map((post) => (
          <div
            key={post.post_id}
            className="rounded-xl border border-slate-800 bg-slate-900 p-4 space-y-2 hover:border-slate-700 transition-colors"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-medium">
                {post.post_type}
              </span>
              {post.tags.slice(0, 3).map((tag) => (
                <span key={tag} className="text-xs text-slate-500">#{tag}</span>
              ))}
            </div>
            <h3 className="font-semibold text-sm">{post.title}</h3>
            <p className="text-sm text-slate-400 line-clamp-2">{post.content}</p>
          </div>
        ))}

        {!loading && filtered.length === 0 && (
          <div className="text-center py-16 text-slate-500">
            <MessageSquare className="w-8 h-8 mx-auto mb-3 opacity-30" />
            <p>No posts found.</p>
          </div>
        )}
      </div>

      {filtered.length >= limit && (
        <button
          onClick={() => setLimit((l) => l + 20)}
          className="w-full py-3 mt-4 text-sm text-slate-400 hover:bg-slate-800 rounded-lg transition-colors"
        >
          Load more
        </button>
      )}
    </AppShell>
  );
}
