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
import { ArrowLeft, Loader2 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { PostCard } from "@/components/feed/PostCard";
import { SocialComposeBox } from "@/components/feed/SocialComposeBox";
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

  // Load replies
  useEffect(() => {
    let active = true;
    (async () => {
      setReplyLoading(true);
      try {
        const token = getToken() ?? undefined;
        const data = await getPostReplies(id, { limit: 50 }, token);
        if (active) setReplies(data.posts.map(toSocialPost));
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

      {root && (
        <div className="mb-6">
          <PostCard post={root} index={0} />
        </div>
      )}

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
          visibleReplies.map((reply, i) => (
            <PostCard key={reply.post_id} post={reply} index={i} />
          ))}
      </div>
    </AppShell>
  );
}
