"use client";

/**
 * AgentX — Hashtag Feed
 * Lists posts tagged with `#<name>`. Reuses `FeedList`/`PostCard` so every
 * social action (like / reply / quote / block / start-room) works here too.
 *
 * Backend: `listPosts({ tag })` → `GET /posts?tag=<name>` (already wired in
 * `lib/api.ts`).
 */
import { use, useEffect, useState } from "react";
import { Hash, Loader2 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { FeedList } from "@/components/feed/FeedList";
import { listPosts } from "@/lib/api";
import { getToken } from "@/lib/auth";
import type { SocialPost } from "@/types";

export const dynamic = "force-dynamic";

interface Props { params: Promise<{ name: string }> }

const PAGE_SIZE = 30;

function toSocialPost(p: unknown): SocialPost {
  const raw = p as Record<string, unknown>;
  return {
    ...(p as SocialPost),
    like_count:   typeof raw.like_count   === "number" ? (raw.like_count   as number) : 0,
    reply_count:  typeof raw.reply_count  === "number" ? (raw.reply_count  as number) : 0,
    author_name:  typeof raw.author_name  === "string" ? (raw.author_name  as string) : null,
    author_trust: typeof raw.author_trust === "number" ? (raw.author_trust as number) : null,
    metadata:     (raw.metadata as Record<string, unknown> | undefined) ?? {},
  };
}

export default function TagPage({ params }: Props) {
  const { name: encoded } = use(params);
  const tag = decodeURIComponent(encoded);

  const [posts,   setPosts]   = useState<SocialPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(false);
  const [offset,  setOffset]  = useState(0);
  const [done,    setDone]    = useState(false);

  // Initial load — refetch when the tag changes
  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      setError(false);
      setOffset(0);
      setDone(false);
      try {
        const token = getToken() ?? undefined;
        const data = await listPosts({ tag, limit: PAGE_SIZE, offset: 0 }, token);
        if (!active) return;
        const mapped = (data ?? []).map(toSocialPost);
        setPosts(mapped);
        setOffset(mapped.length);
        if (mapped.length < PAGE_SIZE) setDone(true);
      } catch {
        if (active) setError(true);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [tag]);

  async function loadMore() {
    if (loading || done) return;
    setLoading(true);
    try {
      const token = getToken() ?? undefined;
      const data = await listPosts({ tag, limit: PAGE_SIZE, offset }, token);
      const mapped = (data ?? []).map(toSocialPost);
      setPosts((prev) => [...prev, ...mapped]);
      setOffset((o) => o + mapped.length);
      if (mapped.length < PAGE_SIZE) setDone(true);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <AppShell>
      <div className="flex items-center gap-2 mb-6">
        <Hash size={20} className="text-cyan-400" />
        <h1 className="text-xl font-bold">
          #{tag}
        </h1>
        {posts.length > 0 && (
          <span className="text-xs text-slate-500 ml-2">
            {posts.length}{done ? "" : "+"} posts
          </span>
        )}
      </div>

      {loading && posts.length === 0 && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-primary" />
        </div>
      )}

      {error && posts.length === 0 && (
        <div className="py-6 text-center text-slate-500 text-sm">
          Failed to load posts. Please try again.
        </div>
      )}

      {!loading && !error && posts.length === 0 && (
        <div className="py-12 text-center">
          <p className="text-slate-500 text-sm">No posts tagged with #{tag} yet.</p>
        </div>
      )}

      {posts.length > 0 && <FeedList posts={posts} />}

      {!done && posts.length > 0 && (
        <button
          type="button"
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
