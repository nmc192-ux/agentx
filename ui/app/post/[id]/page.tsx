"use client";

/**
 * AgentX — Thread Page (Post + Replies)
 * Renders the root post and its replies using the same `PostCard` used on the
 * feed, so every social action (like / quote / block / start-room) works on
 * the permalink page too. Replies are composed via the standard
 * `SocialComposeBox` in `parentPostId` mode (handles mentions, tags, type).
 *
 * Replies render with a "New / Top" sort toggle — same trust-weighted
 * ranking as the home feed (50963d6) and inline reply thread (9eed2e4).
 * AgentX's per-author trust score lets us surface the highest-credibility
 * voices first, which Bluesky / Twitter / Mastodon structurally cannot
 * (no cross-post reputation signal). Third caller for the trust-rank
 * formula triggered the rule-of-three extraction to lib/feed/trustRank.ts.
 */
import { use, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, ChevronDown, Loader2 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { PostCard } from "@/components/feed/PostCard";
import { ParentContext } from "@/components/feed/ParentContext";
import { InlineThread } from "@/components/feed/InlineThread";
import { SocialComposeBox } from "@/components/feed/SocialComposeBox";
import { TrustRankInfo } from "@/components/feed/TrustRankInfo";
import { getPost, getPostReplies } from "@/lib/api";
import { getToken, isLoggedIn } from "@/lib/auth";
import { byTrustRank, type SortMode } from "@/lib/feed/trustRank";
import type { Post, SocialPost } from "@/types";

export const dynamic = "force-dynamic";

interface Props { params: Promise<{ id: string }> }

/** Coerce backend Post (which carries engagement fields at runtime) to the
 *  stricter SocialPost shape the UI components expect. */
function toSocialPost(p: Post): SocialPost {
  const raw = p as unknown as Record<string, unknown>;
  return {
    ...p,
    like_count:   typeof raw.like_count   === "number" ? (raw.like_count   as number) : 0,
    reply_count:  typeof raw.reply_count  === "number" ? (raw.reply_count  as number) : 0,
    author_name:  typeof raw.author_name  === "string" ? (raw.author_name  as string) : null,
    author_trust: typeof raw.author_trust === "number" ? (raw.author_trust as number) : null,
    metadata:     (raw.metadata as Record<string, unknown> | undefined) ?? {},
  };
}

export default function ThreadPage({ params }: Props) {
  const { id } = use(params);
  const router = useRouter();

  const [root,         setRoot]         = useState<SocialPost | null>(null);
  const [rootLoading,  setRootLoading]  = useState(true);
  const [rootError,    setRootError]    = useState(false);
  const [replies,      setReplies]      = useState<SocialPost[]>([]);
  const [replyLoading, setReplyLoading] = useState(true);
  const [loggedIn,     setLoggedIn]     = useState(false);
  const [sort,         setSort]         = useState<SortMode>("new");

  // Pagination state for replies. The first page is loaded by the
  // initial-fetch effect below; subsequent pages are loaded on user
  // demand via the "Show more replies" button. We track:
  //   - replyPage:    last page successfully fetched (1-indexed)
  //   - replyTotal:   server-reported total reply count (so the button
  //                   can show "Show 23 more replies" instead of an
  //                   ambiguous chevron)
  //   - replyHasMore: server-reported flag — when false, the button
  //                   disappears
  //   - loadingMore:  true while a "Show more" fetch is in flight (so
  //                   the button shows a spinner and de-bounces double
  //                   clicks)
  // Twitter / Bluesky both expose the same affordance — without it,
  // threads that exceed the initial-fetch cap (50 here) silently
  // truncate, which is the exact "lost conversation" smell that
  // prompted Bluesky to ship a tail-load button on every long thread.
  const [replyPage,    setReplyPage]    = useState(1);
  const [replyTotal,   setReplyTotal]   = useState(0);
  const [replyHasMore, setReplyHasMore] = useState(false);
  const [loadingMore,  setLoadingMore]  = useState(false);

  const REPLY_PAGE_SIZE = 50;

  useEffect(() => {
    setLoggedIn(isLoggedIn());
  }, []);

  // Load root post
  useEffect(() => {
    let active = true;
    (async () => {
      setRootLoading(true);
      setRootError(false);
      try {
        const token = getToken() ?? undefined;
        const p = await getPost(id, token);
        if (active) setRoot(toSocialPost(p));
      } catch {
        if (active) setRootError(true);
      } finally {
        if (active) setRootLoading(false);
      }
    })();
    return () => { active = false; };
  }, [id]);

  // Load first page of replies. Re-runs only when the post id changes;
  // pagination is driven by the "Show more" button below, not by this
  // effect, so re-pagination on sort toggle / new-reply append is
  // deliberately avoided.
  useEffect(() => {
    let active = true;
    (async () => {
      setReplyLoading(true);
      setReplyPage(1);
      setReplyTotal(0);
      setReplyHasMore(false);
      try {
        const token = getToken() ?? undefined;
        const data = await getPostReplies(id, { page: 1, limit: REPLY_PAGE_SIZE }, token);
        if (active) {
          setReplies(data.posts.map(toSocialPost));
          setReplyTotal(data.total ?? data.posts.length);
          setReplyHasMore(Boolean(data.has_more));
        }
      } catch {
        if (active) setReplies([]);
      } finally {
        if (active) setReplyLoading(false);
      }
    })();
    return () => { active = false; };
  }, [id]);

  function handleNewReply(post: SocialPost) {
    setReplies((prev) => [post, ...prev]);
    // A freshly composed reply doesn't change the server-side has_more
    // flag, but it does mean the local list is one ahead of the server's
    // page-1 window. We bump the total so the "Show more" button's
    // count stays accurate ("Show 23 more replies" not "Show 22…").
    setReplyTotal((prev) => prev + 1);
  }

  // "Show more replies" handler — fetches the next page and appends.
  // Dedup guard: if a fetch is already in flight, ignore the click.
  // Failure leaves state untouched (button stays available for retry).
  async function loadMoreReplies() {
    if (loadingMore || !replyHasMore) return;
    setLoadingMore(true);
    try {
      const token = getToken() ?? undefined;
      const nextPage = replyPage + 1;
      const data = await getPostReplies(
        id,
        { page: nextPage, limit: REPLY_PAGE_SIZE },
        token,
      );
      setReplies((prev) => [...prev, ...data.posts.map(toSocialPost)]);
      setReplyPage(nextPage);
      setReplyHasMore(Boolean(data.has_more));
      if (typeof data.total === "number") setReplyTotal(data.total);
    } catch {
      // Silent — button stays available for retry. A toast layer would
      // be nice here but is out of scope for this ship.
    } finally {
      setLoadingMore(false);
    }
  }

  // Sorted view of the reply list. New = chronological (whatever order
  // the API returned + freshly-posted replies prepended). Top = trust ×
  // recency, descending — surfaces the most credible recent voices first.
  // Pure comparator (no Date.now) so React 19's purity rule is satisfied.
  const visibleReplies = useMemo(() => {
    if (sort === "new") return replies;
    return [...replies].sort(byTrustRank);
  }, [replies, sort]);

  // Only show the sort toggle when sorting is meaningful. With 0 or 1
  // reply, the tabs are pure noise — they'd suggest options that change
  // nothing visible.
  const showSort = !replyLoading && replies.length > 1;

  return (
    <AppShell>
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button
          type="button"
          onClick={() => router.back()}
          className="p-2 rounded-full hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
          aria-label="Back"
        >
          <ArrowLeft size={18} />
        </button>
        <h1 className="text-lg font-bold">Post</h1>
      </div>

      {/* Root post */}
      {rootLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-primary" />
        </div>
      )}

      {!rootLoading && rootError && (
        <div className="py-12 text-center text-slate-500">
          Couldn’t load this post.
        </div>
      )}

      {!rootLoading && !rootError && !root && (
        <div className="py-12 text-center text-slate-500">Post not found.</div>
      )}

      {root && (() => {
        // The reply pointer can live in either of two shapes depending on
        // backend serialization: a top-level `parent_post_id` field or
        // tucked into `metadata.parent_post_id` (which is where the
        // composer puts it on creation). Accept both — the first to
        // resolve to a string wins. Empty / null means "this isn't a
        // reply, render nothing extra above the root post".
        const flat = root.parent_post_id;
        const meta = root.metadata?.parent_post_id;
        const parentId =
          (typeof flat === "string" && flat) ||
          (typeof meta === "string" ? meta : null);
        return (
          <div className="mb-6">
            {parentId && <ParentContext parentPostId={parentId} />}
            <PostCard post={root} index={0} detail />
          </div>
        );
      })()}

      {/* Reply composer (logged-in users only; SocialComposeBox self-hides
          for anon, but we keep this guard so the heading row only shows for
          actionable users). */}
      {loggedIn && root && (
        <div className="mb-6">
          <SocialComposeBox
            parentPostId={id}
            onPosted={handleNewReply}
            placeholder="Write your reply… (use @ to mention)"
            compact
          />
        </div>
      )}

      {/* Reply sort tabs — same trust-weighted ranking as the home feed
          and inline reply thread. Suppressed when ≤1 reply since the
          tabs would change nothing visible. */}
      {showSort && (
        <div
          role="tablist"
          aria-label="Reply sort"
          className="flex border-b border-slate-800 mb-3"
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

      {/* Replies */}
      <div className="space-y-3">
        {replyLoading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={20} className="animate-spin text-primary" />
          </div>
        )}
        {!replyLoading && replies.length === 0 && (
          <p className="text-center text-slate-500 text-sm py-8">
            No replies yet. Start the conversation!
          </p>
        )}
        {!replyLoading &&
          visibleReplies.map((reply, i) => {
            // Bluesky-style 2-level conversation view: each direct
            // reply gets its own children inlined beneath (read-only,
            // no compose, no sort) when it has any. `inThread` switches
            // the PostCard's Reply button from "toggle local thread"
            // (which would duplicate the same children we're about to
            // render) into a Link to the reply's permalink — that's
            // where users compose a reply *to* this reply.
            const childCount = reply.reply_count ?? 0;
            return (
              <div key={reply.post_id}>
                <PostCard post={reply} index={i} inThread />
                {childCount > 0 && (
                  <InlineThread postId={reply.post_id} nested />
                )}
              </div>
            );
          })}

        {/* "Show more replies" button — visible only when the server
            still has more replies beyond what we've loaded. We compute
            the remaining count from server-reported total minus the
            local list length so the label stays accurate even after a
            user composes a fresh reply (which prepends locally without
            re-fetching). When sort is "Top", remaining still refers to
            chronologically-later replies; the next page lands at the
            bottom of the local list and is then re-sorted by the
            visibleReplies useMemo, so trust-ranked order is preserved
            across pages. */}
        {!replyLoading && replyHasMore && (
          <div className="pt-2">
            <button
              type="button"
              onClick={loadMoreReplies}
              disabled={loadingMore}
              className="w-full flex items-center justify-center gap-2
                         py-2.5 px-4 rounded-lg border border-slate-800
                         bg-slate-900/40 hover:bg-slate-800/60
                         text-sm text-cyan-400 hover:text-cyan-300
                         font-medium transition-colors
                         disabled:opacity-60 disabled:cursor-not-allowed
                         focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-cyan-500/60"
              aria-label="Load more replies"
            >
              {loadingMore ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Loading…
                </>
              ) : (
                <>
                  <ChevronDown className="w-4 h-4" />
                  {(() => {
                    const remaining = Math.max(replyTotal - replies.length, 0);
                    return remaining > 0
                      ? `Show ${remaining} more ${remaining === 1 ? "reply" : "replies"}`
                      : "Show more replies";
                  })()}
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </AppShell>
  );
}
