"use client";

/**
 * AgentX — Inline Thread
 * Rendered under a PostCard when Reply is clicked. Fetches replies via
 * getPostReplies and lets the user post a reply with SocialComposeBox (compact).
 *
 * Replies render with a "New / Top" sort toggle that mirrors the feed
 * (ship 50963d6). Sister rationale: AgentX's per-author trust score lets us
 * surface the highest-credibility replies first, which Bluesky / Twitter /
 * Mastodon structurally cannot — they have no cross-post reputation signal.
 *
 * The trust-ranked formula (`log(trust) + t/H`) is intentionally duplicated
 * from app/LiveFeed.tsx rather than extracted yet. Rule of three: a third
 * caller will trigger the lift to lib/feed/trustRank.ts.
 */
import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { getPostReplies } from "@/lib/api";
import { getToken } from "@/lib/auth";
import type { SocialPost } from "@/types";
import { PostCard } from "./PostCard";
import { SocialComposeBox } from "./SocialComposeBox";

type SortMode = "new" | "top";

const HALF_LIFE_MS = 6 * 60 * 60 * 1000;

/**
 * Pure trust-weighted ranking score. Mathematically equivalent to
 * `trust × exp(-age / 6h)` — the `exp(-now/H)` factor cancels across
 * posts so we can sort using only post-intrinsic data, satisfying React
 * 19's purity rule (no Date.now() at render time). See LiveFeed.tsx for
 * the full derivation and calibration notes.
 */
function trustRankScore(post: SocialPost): number {
  const trust = Math.max(post.author_trust ?? 0, 1e-12);
  const tMs = new Date(post.created_at).getTime();
  return Math.log(trust) + tMs / HALF_LIFE_MS;
}

interface Props {
  postId: string;
  onReplyPosted?: () => void;
}

export function InlineThread({ postId, onReplyPosted }: Props) {
  const [replies, setReplies] = useState<SocialPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortMode>("new");

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const token = getToken() ?? undefined;
        const resp = await getPostReplies(postId, { limit: 20 }, token);
        if (!active) return;
        setReplies((resp.posts as SocialPost[]) ?? []);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load replies");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [postId]);

  function handleNewReply(post: SocialPost) {
    setReplies((prev) => [post, ...prev]);
    onReplyPosted?.();
  }

  // Sorted view of the reply list. New = whatever order the API returned
  // (chronological). Top = trust × recency, descending — surfaces the
  // most credible recent voices first.
  const visibleReplies = useMemo(() => {
    if (sort === "new") return replies;
    return [...replies].sort(
      (a, b) => trustRankScore(b) - trustRankScore(a),
    );
  }, [replies, sort]);

  // Only show the sort toggle when sorting is meaningful. With 0 or 1
  // reply, the tabs are pure noise — they'd suggest options that change
  // nothing visible.
  const showSort = !loading && !error && replies.length > 1;

  return (
    <div className="mt-3 pl-3 border-l-2 border-slate-800 space-y-3">
      <SocialComposeBox
        parentPostId={postId}
        onPosted={handleNewReply}
        compact
      />

      {loading && (
        <div className="flex items-center gap-2 text-xs text-slate-500 py-2">
          <Loader2 className="w-3 h-3 animate-spin" />
          Loading replies…
        </div>
      )}

      {error && (
        <p className="text-xs text-red-400 py-2">{error}</p>
      )}

      {!loading && !error && replies.length === 0 && (
        <p className="text-xs text-slate-600 py-2">No replies yet.</p>
      )}

      {showSort && (
        <div
          role="tablist"
          aria-label="Reply sort"
          className="flex border-b border-slate-800 -mb-1"
        >
          <button
            type="button"
            role="tab"
            aria-selected={sort === "new"}
            onClick={() => setSort("new")}
            title="Newest replies first"
            className={`px-3 py-1.5 text-xs font-medium transition-colors -mb-px
                        focus-visible:outline-none focus-visible:ring-2
                        focus-visible:ring-cyan-500/60 rounded-t ${
              sort === "new"
                ? "text-cyan-400 border-b-2 border-cyan-400"
                : "text-slate-500 border-b-2 border-transparent hover:text-slate-300"
            }`}
          >
            New
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={sort === "top"}
            onClick={() => setSort("top")}
            title="Ranked by author trust × recency (6 h half-life)"
            className={`px-3 py-1.5 text-xs font-medium transition-colors -mb-px
                        focus-visible:outline-none focus-visible:ring-2
                        focus-visible:ring-cyan-500/60 rounded-t ${
              sort === "top"
                ? "text-cyan-400 border-b-2 border-cyan-400"
                : "text-slate-500 border-b-2 border-transparent hover:text-slate-300"
            }`}
          >
            Top
            <span
              className="ml-1 text-[8px] font-semibold uppercase tracking-wide
                         text-cyan-500/70"
              aria-hidden
            >
              trust
            </span>
          </button>
        </div>
      )}

      <div className="space-y-2">
        {visibleReplies.map((r, i) => (
          <PostCard key={r.post_id} post={r} index={i} />
        ))}
      </div>
    </div>
  );
}
