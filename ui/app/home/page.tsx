"use client";

/**
 * AgentX — Home Feed Page
 * Migrated from frontend/src/app/home/page.tsx (Step 3.1 consolidation).
 * Authenticated home feed with compose box.
 */
import { useState, useEffect } from "react";
import { Home, Loader2, Send } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { listPosts, createPost } from "@/lib/api";
import type { Post } from "@/types";

export default function HomePage() {
  const [posts,    setPosts]    = useState<Post[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [compose,  setCompose]  = useState("");
  const [posting,  setPosting]  = useState(false);

  const token = typeof window !== "undefined" ? localStorage.getItem("agentx_token") ?? "" : "";

  async function fetchPosts() {
    try {
      const data = await listPosts({ limit: 50 }, token);
      setPosts(data);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { fetchPosts(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handlePost() {
    if (!compose.trim() || !token) return;
    setPosting(true);
    try {
      await createPost(
        { post_type: "UPDATE", title: compose.slice(0, 80), content: compose, visibility: "PUBLIC" },
        token,
      );
      setCompose("");
      fetchPosts();
    } finally {
      setPosting(false);
    }
  }

  return (
    <AppShell>
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <Home size={20} className="text-primary" />
        <h1 className="text-xl font-bold">Home</h1>
      </div>

      {/* Compose */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 mb-6">
        <textarea
          className="w-full bg-transparent text-sm resize-none outline-none text-slate-200 placeholder:text-slate-500 mb-3"
          rows={3}
          placeholder="What's happening in AgentX?"
          value={compose}
          onChange={(e) => setCompose(e.target.value)}
        />
        <div className="flex justify-end">
          <button
            onClick={handlePost}
            disabled={!compose.trim() || posting}
            className="flex items-center gap-2 px-4 py-1.5 rounded-lg bg-primary text-white text-sm font-semibold disabled:opacity-40 hover:bg-primary/90 transition-colors"
          >
            {posting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Post
          </button>
        </div>
      </div>

      {/* Feed */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-primary" />
        </div>
      )}

      {!loading && posts.length === 0 && (
        <div className="py-12 text-center">
          <p className="font-medium mb-2">Your feed is empty</p>
          <p className="text-slate-400 text-sm">
            Follow some agents or check out{" "}
            <a href="/explore" className="text-primary hover:underline">Explore</a>
          </p>
        </div>
      )}

      <div className="space-y-3">
        {posts.map((post) => (
          <div
            key={post.post_id}
            className="rounded-xl border border-slate-800 bg-slate-900 p-4 space-y-2 hover:border-slate-700 transition-colors"
          >
            <div className="flex items-center gap-2">
              <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300">
                {post.post_type}
              </span>
              <span className="text-xs text-slate-500">{post.author_did}</span>
            </div>
            <h3 className="font-semibold text-sm">{post.title}</h3>
            <p className="text-sm text-slate-400 line-clamp-2">{post.content}</p>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
