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
 * The trust-ranked formula lives in lib/feed/trustRank.ts (extracted on
 * the third caller per rule-of-three).
 *
 * 2-LEVEL CONVERSATION VIEW (depth-1 nesting): top-level threads
 * auto-display each reply's *direct children* indented beneath it (read-
 * only, no compose, no sort) so users can scan a conversation without
 * clicking each reply's expand button. Same as Bluesky / Twitter — the
 * thread renders 2 levels by default; deeper drill-down requires opening
 * the child's permalink (Reply button on an in-thread PostCard becomes
 * a Link to /post/[id], suppressing the duplicate inline-thread render
 * that would otherwise stack the same children twice). Limit on the
 * nested fetch is small (3) so a heavy-replied subthread doesn't dump
 * the entire chain inline.
 */
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Loader2 } from "lucide-react";
import { getPostReplies } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { byTrustRank, type SortMode } from "@/lib/feed/trustRank";
import type { SocialPost } from "@/types";
import { PostCard } from "./PostCard";
import { SocialComposeBox } from "./SocialComposeBox";
import { TrustRankInfo } from "./TrustRankInfo";

interface Props {
  postId: string;
  onReplyPosted?: () => void;
  /**
   * Read-only nested-children view rendered under a parent reply. When
   * true: no compose box, no sort tabs, smaller fetch limit, deeper
   * indent — and we don't recurse another level (caps the thread at 2
   * visible levels). When false: full root-level thread UI.
   */
  nested?: boolean;
}

// How many grandchildren to fetch in nested mode. Small on purpose — a
// chain with hundreds of grandchildren shouldn't dump the whole thing
// inline; users can click "View this reply →" to drill in via permalink.
const NESTED_FETCH_LIMIT = 3;
const ROOT_FETCH_LIMIT = 20;

export function InlineThread({ postId, onReplyPosted, nested = false }: Props) {
  const [replies, setReplies] = useState<SocialPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortMode>("new");

  // Server-reported overflow signal. The inline thread is intentionally
  // a *preview* — we don't paginate here (that would defeat the
  // compactness goal); instead we surface a "View N more on permalink"
  // footer link when the server still has more replies beyond the
  // initial fetch limit. Without this, users land on the inline thread
  // and have no signal that more conversation exists, so a popular
  // post with 200 replies looks identical to a sparse one with 20.
  // Bluesky / Twitter both surface an overflow link from preview
  // threads into the canonical full view for the same reason.
  const [hasMore, setHasMore] = useState(false);
  const [totalReplies, setTotalReplies] = useState(0);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      setError(null);
      setHasMore(false);
      setTotalReplies(0);
      try {
        const token = getToken() ?? undefined;
        const limit = nested ? NESTED_FETCH_LIMIT : ROOT_FETCH_LIMIT;
        const resp = await getPostReplies(postId, { limit }, token);
        if (!active) return;
        setReplies((resp.posts as SocialPost[]) ?? []);
        setHasMore(Boolean(resp.has_more));
        setTotalReplies(resp.total ?? resp.posts?.length ?? 0);
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
  }, [postId, nested]);

  function handleNewReply(post: SocialPost) {
    setReplies((prev) => [post, ...prev]);
    onReplyPosted?.();
  }

  // Sorted view of the reply list. New = whatever order the API returned
  // (chronological). Top = trust × recency, descending — surfaces the
  // most credible recent voices first.
  const visibleReplies = useMemo(() => {
    if (sort === "new") return replies;
    return [...replies].sort(byTrustRank);
  }, [replies, sort]);

  // Only show the sort toggle when sorting is meaningful. With 0 or 1
  // reply, the tabs are pure noise — they'd suggest options that change
  // nothing visible. Suppressed entirely in nested mode (read-only view).
  const showSort = !nested && !loading && !error && replies.length > 1;

  // Outer container styling differs by mode:
  //  - root: standard left-border indent (existing behavior)
  //  - nested: smaller padding, deeper-nested look, less margin so the
  //    nested thread visually clusters with its parent reply
  const containerClass = nested
    ? "mt-2 ml-3 pl-3 border-l border-slate-800/60 space-y-2"
    : "mt-3 pl-3 border-l-2 border-slate-800 space-y-3";

  return (
    <div className={containerClass}>
      {/* Compose box only at root — nested thread is read-only; user
          replies to a grandchild by opening its permalink (PostCard's
          Reply button becomes a Link in inThread mode). */}
      {!nested && (
        <SocialComposeBox
          parentPostId={postId}
          onPosted={handleNewReply}
          compact
        />
      )}

      {loading && (
        <div className="flex items-center gap-2 text-xs text-slate-500 py-2">
          <Loader2 className="w-3 h-3 animate-spin" />
          {nested ? "Loading replies…" : "Loading replies…"}
        </div>
      )}

      {error && (
        <p className="text-xs text-red-400 py-2">{error}</p>
      )}

      {!loading && !error && replies.length === 0 && !nested && (
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
          <TrustRankInfo />
        </div>
      )}

      <div className={nested ? "space-y-1.5" : "space-y-2"}>
        {visibleReplies.map((r, i) => {
          // Auto-show this reply's direct children one level deep, but
          // only at the root level — nested replies don't recurse again
          // (caps total visible depth at 2). The grandchild thread is
          // read-only (no compose, no sort) and only appears when this
          // reply actually has children.
          const childCount = r.reply_count ?? 0;
          return (
            <div key={r.post_id}>
              <PostCard post={r} index={i} inThread />
              {!nested && childCount > 0 && (
                <InlineThread postId={r.post_id} nested />
              )}
            </div>
          );
        })}

        {/* Overflow link — visible only when the server still has more
            replies beyond the inline-preview cap. Computes remaining
            count from server-reported total minus the locally rendered
            list (after a fresh user-composed reply is prepended, the
            local list grows by 1 but server total hasn't, so we floor
            at 0 to avoid a "View -1 more" oddity). Compact size for
            nested mode so the visual nesting cluster doesn't get
            visually heavy. The /post/[id] page is the canonical full
            thread view — paginated, sortable, composable — so this is
            a one-way drill-in: clicking takes the user out of the feed
            into the dedicated thread surface. */}
        {!loading && !error && hasMore && (
          <Link
            href={`/post/${postId}`}
            className={`flex items-center gap-1.5 ${
              nested ? "ml-1 px-2 py-1 text-[11px]" : "px-2.5 py-1.5 text-xs"
            } rounded-md text-cyan-400 hover:text-cyan-300
              hover:bg-cyan-500/5 transition-colors w-fit
              focus-visible:outline-none focus-visible:ring-2
              focus-visible:ring-cyan-500/60`}
            aria-label={`View full thread on permalink (${Math.max(
              totalReplies - replies.length,
              0,
            )} more replies)`}
          >
            {(() => {
              const remaining = Math.max(totalReplies - replies.length, 0);
              if (remaining === 0) return "View full thread";
              return remaining === 1
                ? "View 1 more reply on permalink"
                : `View ${remaining} more replies on permalink`;
            })()}
            <ArrowRight className={nested ? "w-2.5 h-2.5" : "w-3 h-3"} />
          </Link>
        )}
      </div>
    </div>
  );
}
