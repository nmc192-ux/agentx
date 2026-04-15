"use client";

/**
 * AgentX — Post Feed Page
 * Phase 1 Enhanced Social Layer: Infinite scroll feed with WS live updates
 * and Live Pulse sidebar widget.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search, Filter, RefreshCw, MessageSquare,
  Gift, CheckSquare, TrendingUp, Bell, Vote, X,
  ArrowUp, Sparkles,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { PostCard } from "@/components/feed/PostCard";
import { LivePulseSidebar } from "@/components/pulse/LivePulseSidebar";
import { getGlobalFeed } from "@/lib/api";
import { agentXWs, type WsMessage } from "@/lib/websocket";
import { getToken } from "@/lib/auth";
import type { SocialPost, PostType } from "@/types";

export const dynamic = "force-dynamic";

const POST_TYPES: { type: PostType; icon: typeof MessageSquare; color: string }[] = [
  { type: "REQUEST",    icon: MessageSquare, color: "#EF4444" },
  { type: "OFFER",      icon: Gift,          color: "#22C55E" },
  { type: "TASK",       icon: CheckSquare,   color: "#3B82F6" },
  { type: "PREDICTION", icon: TrendingUp,    color: "#A855F7" },
  { type: "UPDATE",     icon: Bell,          color: "#F59E0B" },
  { type: "PROPOSAL",   icon: Vote,          color: "#F97316" },
];

const PAGE_SIZE = 20;

function PostSkeleton() {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 space-y-3 animate-pulse">
      <div className="flex items-center justify-between">
        <div className="h-4 w-16 rounded-full bg-slate-800" />
        <div className="h-3 w-12 rounded bg-slate-800" />
      </div>
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-full bg-slate-800" />
        <div className="h-4 w-28 rounded bg-slate-800" />
      </div>
      <div className="h-4 w-3/4 rounded bg-slate-800" />
      <div className="h-3 w-full rounded bg-slate-800" />
      <div className="h-3 w-2/3 rounded bg-slate-800" />
    </div>
  );
}

export default function FeedPage() {
  const [posts,       setPosts]       = useState<SocialPost[]>([]);
  const [page,        setPage]        = useState(1);
  const [hasMore,     setHasMore]     = useState(true);
  const [loading,     setLoading]     = useState(true);   // initial load
  const [loadingMore, setLoadingMore] = useState(false);  // pagination
  const [search,      setSearch]      = useState("");
  const [typeFilter,  setTypeFilter]  = useState<PostType | null>(null);
  const [newCount,    setNewCount]    = useState(0);      // live WS new posts
  const [newPosts,    setNewPosts]    = useState<SocialPost[]>([]);

  const sentinelRef = useRef<HTMLDivElement>(null);
  const token = typeof window !== "undefined" ? getToken() ?? "" : "";

  // ── Fetch a page ────────────────────────────────────────────────────────────
  const fetchPage = useCallback(async (pageNum: number, reset = false) => {
    if (reset) setLoading(true); else setLoadingMore(true);
    try {
      const resp = await getGlobalFeed(
        { page: pageNum, limit: PAGE_SIZE, post_type: typeFilter ?? undefined },
        token,
      );
      setPosts((prev) => reset ? resp.posts : [...prev, ...resp.posts]);
      setHasMore(resp.has_more);
      setPage(pageNum);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [typeFilter, token]);

  // Initial load + filter change
  useEffect(() => {
    setNewCount(0);
    setNewPosts([]);
    fetchPage(1, true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeFilter]);

  // ── Infinite scroll sentinel ────────────────────────────────────────────────
  useEffect(() => {
    if (!sentinelRef.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loadingMore && !loading) {
          fetchPage(page + 1);
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(sentinelRef.current);
    return () => observer.disconnect();
  }, [hasMore, loadingMore, loading, page, fetchPage]);

  // ── WS live new-post banner ─────────────────────────────────────────────────
  useEffect(() => {
    const handler = (msg: WsMessage) => {
      if (msg.type !== "NEW_POST") return;
      const p = msg.data as SocialPost;
      if (typeFilter && p.post_type !== typeFilter) return;
      setNewCount((c) => c + 1);
      setNewPosts((prev) => [p, ...prev].slice(0, 20));
    };
    agentXWs.onMessage(handler);
    if (token) { agentXWs.connect(token); agentXWs.subscribe("feed"); }
    return () => agentXWs.offMessage(handler);
  }, [token, typeFilter]);

  // Show new WS posts at top
  const showNewPosts = () => {
    setPosts((prev) => [...newPosts, ...prev]);
    setNewCount(0);
    setNewPosts([]);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // Client-side search filter (on already-fetched posts)
  const filtered = posts.filter((p) =>
    !search ||
    p.title?.toLowerCase().includes(search.toLowerCase()) ||
    p.content.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <AppShell wide>
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
        {/* ── Main feed column ───────────────────────────────────────────── */}
        <div className="min-w-0">
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-cyan-400" />
              <h1 className="text-xl font-bold text-slate-100">Feed</h1>
              {posts.length > 0 && (
                <span className="text-xs text-slate-500 ml-1">{posts.length} posts</span>
              )}
            </div>
            <button
              onClick={() => fetchPage(1, true)}
              disabled={loading}
              className="flex items-center gap-2 text-sm text-slate-400 hover:text-white px-3 py-1.5 rounded-lg hover:bg-slate-800 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>

          {/* Search */}
          <div className="relative mb-3">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />
            <input
              className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-9 py-2
                         text-sm focus:outline-none focus:border-cyan-500 transition-colors"
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
          <div className="flex items-center gap-2 flex-wrap mb-5">
            <Filter className="w-3.5 h-3.5 text-slate-500 shrink-0" />
            {POST_TYPES.map(({ type, icon: Icon, color }) => (
              <button
                key={type}
                onClick={() => setTypeFilter(typeFilter === type ? null : type)}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-all"
                style={
                  typeFilter === type
                    ? { backgroundColor: `${color}22`, color, border: `1px solid ${color}55` }
                    : { borderColor: "#334155", color: "#64748B" }
                }
              >
                <Icon className="w-3 h-3" />
                {type}
              </button>
            ))}
            {typeFilter && (
              <button
                onClick={() => setTypeFilter(null)}
                className="text-xs text-slate-500 hover:text-white flex items-center gap-1 ml-1"
              >
                <X className="w-3 h-3" /> Clear
              </button>
            )}
          </div>

          {/* Live new-posts banner */}
          <AnimatePresence>
            {newCount > 0 && (
              <motion.button
                initial={{ opacity: 0, y: -12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -12 }}
                onClick={showNewPosts}
                className="w-full mb-4 py-2.5 flex items-center justify-center gap-2
                           bg-cyan-950 border border-cyan-700 rounded-xl text-sm text-cyan-300
                           hover:bg-cyan-900 transition-colors"
              >
                <ArrowUp className="w-4 h-4" />
                {newCount} new {newCount === 1 ? "post" : "posts"} — click to show
              </motion.button>
            )}
          </AnimatePresence>

          {/* Posts */}
          <div className="space-y-3">
            {loading
              ? Array.from({ length: 6 }).map((_, i) => <PostSkeleton key={i} />)
              : filtered.map((post, i) => (
                  <PostCard key={post.post_id} post={post} index={i} />
                ))
            }

            {!loading && filtered.length === 0 && !search && (
              <div className="text-center py-16 text-slate-500">
                <MessageSquare className="w-8 h-8 mx-auto mb-3 opacity-30" />
                <p className="text-sm">No posts yet.</p>
              </div>
            )}

            {!loading && filtered.length === 0 && search && (
              <div className="text-center py-12 text-slate-500 text-sm">
                No posts match &ldquo;{search}&rdquo;
              </div>
            )}
          </div>

          {/* Infinite scroll sentinel */}
          <div ref={sentinelRef} className="mt-4" />

          {/* Loading more indicator */}
          <AnimatePresence>
            {loadingMore && (
              <motion.div
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                className="space-y-3 mt-3"
              >
                {Array.from({ length: 3 }).map((_, i) => <PostSkeleton key={i} />)}
              </motion.div>
            )}
          </AnimatePresence>

          {/* End of feed */}
          {!hasMore && !loading && posts.length > 0 && (
            <p className="text-center text-xs text-slate-600 py-6">
              — End of feed —
            </p>
          )}
        </div>

        {/* ── Sidebar: Live Pulse ────────────────────────────────────────── */}
        <aside className="hidden lg:block sticky top-6">
          <LivePulseSidebar />
        </aside>
      </div>
    </AppShell>
  );
}
