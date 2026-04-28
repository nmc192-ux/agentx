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
import { Hash, Loader2, Pin, PinOff } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { FeedList } from "@/components/feed/FeedList";
import { PostCardSkeleton } from "@/components/feed/PostCardSkeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { listPosts } from "@/lib/api";
import { getToken } from "@/lib/auth";
import {
  togglePinnedTag,
  usePinnedTags,
  MAX_PINNED,
} from "@/lib/storage/pinnedTags";
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
        <PinTagButton tag={tag} />
      </div>

      {loading && posts.length === 0 && <PostCardSkeleton count={3} />}

      {error && posts.length === 0 && (
        <div className="py-6 text-center text-slate-500 text-sm">
          Failed to load posts. Please try again.
        </div>
      )}

      {!loading && !error && posts.length === 0 && (
        <EmptyState
          icon={<Hash />}
          title={`No posts tagged #${tag} yet`}
          subtitle="Be the first to post with this tag — it'll show up here for everyone to discover."
          primary={{ label: "Trending tags", href: "/explore" }}
          secondary={{ label: "Open feed",   href: "/"        }}
        />
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

/**
 * Pin / Unpin button — toggles whether this tag shows up as a tab on
 * the home feed. Bluesky's "save feed" + Twitter's "list pin" parity.
 * Reads + writes via lib/storage/pinnedTags so the home feed picks
 * up changes through the storage event without a page reload.
 *
 * The button is in `ml-auto` position (pushed to the right of the
 * tag header row) so it doesn't compete with the page title for
 * scanning attention; it's an action, not a label. When the user
 * has hit MAX_PINNED and the tag isn't already pinned, the button
 * disables with an explanatory tooltip rather than silently no-op-ing
 * a click — pin attempts past the cap evict the oldest pin (per the
 * pinTag helper), which we surface to the user via the tooltip so
 * the eviction isn't surprising.
 */
function PinTagButton({ tag }: { tag: string }) {
  const pinnedTags = usePinnedTags();
  const lower = tag.toLowerCase();
  const isPinned = pinnedTags.includes(lower);
  const atCap = !isPinned && pinnedTags.length >= MAX_PINNED;

  const label = isPinned ? "Unpin from home" : "Pin to home";
  const title = isPinned
    ? "Remove this hashtag from the home feed tabs"
    : atCap
      ? `Pinning will replace your oldest pinned tag (#${pinnedTags[0]}). You can have up to ${MAX_PINNED} pinned hashtags.`
      : "Add this hashtag as a tab on the home feed";

  return (
    <button
      type="button"
      onClick={() => togglePinnedTag(tag)}
      title={title}
      aria-pressed={isPinned}
      className={`ml-auto inline-flex items-center gap-1.5 px-3 py-1.5
                  text-xs font-medium rounded-lg transition-colors
                  focus-visible:outline-none focus-visible:ring-2
                  focus-visible:ring-cyan-500/60 ${
        isPinned
          ? "bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 border border-cyan-500/30"
          : "bg-slate-800/60 text-slate-300 hover:bg-slate-800 border border-slate-700"
      }`}
    >
      {isPinned ? (
        <>
          <PinOff className="w-3.5 h-3.5" />
          {label}
        </>
      ) : (
        <>
          <Pin className="w-3.5 h-3.5" />
          {label}
        </>
      )}
    </button>
  );
}
