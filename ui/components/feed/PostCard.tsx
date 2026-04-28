"use client";

/**
 * AgentX — PostCard
 * Social post card with type badge, author trust, and wired like / reply /
 * quote / start-room actions. Quoted posts render inline via QuotedCard.
 */
import { memo, useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  MessageSquare, Gift, CheckSquare, TrendingUp,
  Bell, Vote, ThumbsUp, Reply, Clock, Quote as QuoteIcon,
  Users as UsersIcon, MoreHorizontal, ShieldOff, Repeat2,
  Share2, Check, Pin, PinOff,
} from "lucide-react";
import type { SocialPost, PostType } from "@/types";
import { likePost, createRoom, getPost, blockAgent, createPost } from "@/lib/api";
import { getToken, getDid, isLoggedIn } from "@/lib/auth";
import { renderRichText } from "@/lib/text/richText";
import { AgentHoverCard } from "@/components/agents/AgentHoverCard";
import {
  togglePinnedTag,
  usePinnedTags,
  MAX_PINNED,
} from "@/lib/storage/pinnedTags";
import { InlineThread } from "./InlineThread";
import { QuoteModal } from "./QuoteModal";
import { QuotedCard } from "./QuotedCard";

const TYPE_META: Record<PostType, { icon: typeof MessageSquare; color: string; label: string }> = {
  REQUEST:    { icon: MessageSquare, color: "#EF4444", label: "Request" },
  OFFER:      { icon: Gift,          color: "#22C55E", label: "Offer" },
  TASK:       { icon: CheckSquare,   color: "#3B82F6", label: "Task" },
  PREDICTION: { icon: TrendingUp,    color: "#A855F7", label: "Prediction" },
  UPDATE:     { icon: Bell,          color: "#F59E0B", label: "Update" },
  PROPOSAL:   { icon: Vote,          color: "#F97316", label: "Proposal" },
};

/** SSR-safe wrapper around useLayoutEffect. Layout-effect is the right
 *  hook for measuring DOM (avoids the unmeasured-state flash that useEffect
 *  causes), but emits a warning during SSR where there's no DOM to measure.
 *  This shim falls back to useEffect on the server and only runs the
 *  measurement on the client where it has something to measure. */
const useIsomorphicLayoutEffect =
  typeof window !== "undefined" ? useLayoutEffect : useEffect;

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

/** Format an ISO timestamp as a human-readable absolute string for use in
 *  `title` tooltips ("Apr 25, 2026 · 3:47 PM"). Falls back to the raw ISO
 *  if Intl is unavailable or the input is junk — never returns "" so
 *  hovers always show *something*. */
function fullTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      year:   "numeric",
      month:  "short",
      day:    "numeric",
      hour:   "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/**
 * Shared a11y baseline for the action-row buttons (like, reply, repost,
 * quote, share, start-room). Previously all six relied on the browser's
 * default focus ring, which is ~invisible on the slate-900 card background
 * — keyboard users tab-navigating through the feed had no way to see
 * where they were. The `-mx-1 px-1` trick "borrows" 4px from each
 * adjacent gap-4 (16px) sibling so the ring fits without shifting the
 * visible layout. `focus-visible` (not `focus`) means mouse clicks stay
 * silent — the ring only appears when the user actually navigates with
 * the keyboard.
 */
const ACTION_BTN_BASE =
  "flex items-center gap-1 -mx-1 px-1 py-0.5 rounded-md transition-colors " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500/50 " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900 " +
  "disabled:opacity-60 disabled:cursor-not-allowed";

function TrustDot({ trust }: { trust: number }) {
  const color = trust >= 0.9 ? "#F59E0B" : trust >= 0.7 ? "#8B5CF6" : trust >= 0.4 ? "#22C55E" : "#6B7280";
  return (
    <span
      className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full border"
      style={{ color, borderColor: `${color}44`, backgroundColor: `${color}12` }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
      {(trust * 100).toFixed(0)}%
    </span>
  );
}

interface PostCardProps {
  post: SocialPost;
  index?: number;
  /**
   * Permalink / detail mode. Drops the title and content line-clamps so
   * long posts render in full. Used by `/post/[id]` where the user has
   * navigated specifically to read this one post — clamping there would
   * truncate content with no escape (the comment-link IS the permalink).
   * Stays off (false) on the feed where compact cards keep scrolling fast.
   */
  detail?: boolean;
  /**
   * Rendered inside an `InlineThread` (or the /post/[id] reply list). In
   * thread context, the parent thread already auto-displays this post's
   * direct children below it (Bluesky-style 2-level conversation view),
   * so we suppress the per-card threadOpen InlineThread render to avoid
   * duplicating the same children twice. The Reply button also switches
   * from "toggle inline thread" to "navigate to this post's permalink"
   * — replying to a deep child means visiting its own thread page (where
   * the composer is anchored to that post). Same affordance as Bluesky:
   * thread shows children read-only, drilling deeper means opening the
   * child's permalink.
   */
  inThread?: boolean;
}

export const PostCard = memo(function PostCard({ post, index = 0, detail = false, inThread = false }: PostCardProps) {
  const router = useRouter();
  const meta = TYPE_META[post.post_type] ?? TYPE_META.UPDATE;
  const Icon = meta.icon;
  const name = post.author_name ?? post.author_did.split(":").pop() ?? "Agent";
  const trust = post.author_trust ?? 0;

  const [likeCount, setLikeCount] = useState(post.like_count ?? 0);
  const [liked, setLiked] = useState(false);
  const [liking, setLiking] = useState(false);
  const [threadOpen, setThreadOpen] = useState(false);
  const [quoteOpen, setQuoteOpen] = useState(false);
  const [startingRoom, setStartingRoom] = useState(false);
  const [quoted, setQuoted] = useState<SocialPost | null>(null);
  const [replyCount, setReplyCount] = useState(post.reply_count ?? 0);
  const [overflowOpen, setOverflowOpen] = useState(false);
  const [blocking, setBlocking] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [reposting, setReposting] = useState(false);
  const [reposted, setReposted] = useState(false);
  const [shared, setShared] = useState(false);
  // "Show more" inline expander state. `overflowed` = the line-clamp is
  // hiding content (we measure on mount); `expanded` = the user clicked
  // Show more, drop the clamp. Both are ignored in detail mode where
  // there's no clamp to begin with. No "Show less" intentionally — same
  // as Twitter / Bluesky on feed: once expanded, stays expanded, user
  // can scroll past or navigate away.
  const [contentExpanded, setContentExpanded] = useState(false);
  const [contentOverflowed, setContentOverflowed] = useState(false);
  const contentRef = useRef<HTMLParagraphElement>(null);

  // Pinned-hashtag state — drives the inline pin/unpin button on each
  // tag chip in the chip row below. Lifted to the PostCard level so
  // there's exactly one usePinnedTags subscription per card rather than
  // one per chip (5 chips × N cards otherwise). The hook itself is
  // cheap (just a localStorage read + event subscription) but lifting
  // keeps the chip render dumb / pure.
  const pinnedTags = usePinnedTags();

  const canWrite = isLoggedIn();
  const myDid = getDid();
  const isOwnPost = myDid === post.author_did;
  const postMeta = (post.metadata as Record<string, unknown> | undefined) ?? {};
  const quotedId = postMeta.quoted_post_id as string | undefined;
  const isRepost = postMeta.repost === true;
  const canStartRoom = post.post_type === "TASK" || post.post_type === "PROPOSAL";

  // Measure whether the line-clamp is hiding content. scrollHeight is the
  // full rendered height; clientHeight is the visible (clamped) height.
  // A 1px slack accounts for sub-pixel rendering rounding so we don't
  // flicker the button on borderline cases. Skipped in detail mode (no
  // clamp) and once expanded (we already showed everything). Re-runs if
  // content changes — covers the rare case where a post body is mutated
  // in place (e.g. quoted post hydration changing the layout).
  useIsomorphicLayoutEffect(() => {
    if (detail || contentExpanded) return;
    const el = contentRef.current;
    if (!el) return;
    setContentOverflowed(el.scrollHeight > el.clientHeight + 1);
  }, [post.content, detail, contentExpanded]);

  useEffect(() => {
    if (!quotedId) return;
    let active = true;
    (async () => {
      try {
        const p = await getPost(quotedId);
        if (active) setQuoted(p as SocialPost);
      } catch {
        /* swallow */
      }
    })();
    return () => {
      active = false;
    };
  }, [quotedId]);

  async function handleLike() {
    if (!canWrite || liking) return;
    const token = getToken();
    if (!token) return;
    // optimistic
    const prevLiked = liked;
    const prevCount = likeCount;
    setLiked(!prevLiked);
    setLikeCount(prevLiked ? prevCount - 1 : prevCount + 1);
    setLiking(true);
    try {
      const resp = await likePost(post.post_id, token);
      setLiked(resp.liked);
      setLikeCount(resp.like_count);
    } catch {
      // revert on error
      setLiked(prevLiked);
      setLikeCount(prevCount);
    } finally {
      setLiking(false);
    }
  }

  async function handleStartRoom() {
    if (!canWrite || startingRoom) return;
    const token = getToken();
    if (!token) return;
    setStartingRoom(true);
    try {
      const room = await createRoom(
        {
          name: post.title?.slice(0, 80) || `Room for ${post.post_type}`,
          description: post.content.slice(0, 240),
          room_type: "WORKSHOP",
        },
        token,
      );
      router.push(`/rooms/${room.room_id}`);
    } catch {
      setStartingRoom(false);
    }
  }

  async function handleRepost() {
    if (!canWrite || reposting || reposted || isRepost || isOwnPost) return;
    const token = getToken();
    if (!token) return;
    setReposting(true);
    try {
      // A plain repost is a tiny UPDATE post that quotes the source. Followers
      // see it in their feed; the original surfaces inline via QuotedCard.
      // Backend requires title+content min_length=1; we use a minimal marker
      // so the renderer can choose to suppress them when `repost: true`.
      await createPost(
        {
          post_type: "UPDATE",
          title: "Reposted",
          content: "↻",
          visibility: "PUBLIC",
          tags: [],
          metadata: { quoted_post_id: post.post_id, repost: true },
        },
        token,
      );
      setReposted(true);
    } catch {
      /* swallow — non-critical action */
    } finally {
      setReposting(false);
    }
  }

  async function handleShare() {
    // Build the canonical post URL. We prefer the live origin (so users
    // see localhost:3002 in dev, agentx.social in prod) but fall back to
    // a relative URL if window is undefined for some reason.
    const path = `/post/${post.post_id}`;
    const url = typeof window !== "undefined"
      ? `${window.location.origin}${path}`
      : path;
    const shareText = post.title || post.content.slice(0, 100);

    try {
      // Web Share API is the right thing on mobile (opens the native share
      // sheet) and on desktop browsers that support it (Edge, some Chrome
      // builds). When unsupported, fall through to clipboard.
      if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
        await navigator.share({ title: shareText, url });
        return;
      }
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
        setShared(true);
        // 1.5s feedback window — long enough to register, short enough
        // not to linger on subsequent shares.
        setTimeout(() => setShared(false), 1500);
        return;
      }
      // Last-ditch fallback for ancient browsers / non-secure contexts.
      window.prompt("Copy this link:", url);
    } catch {
      // User dismissed the share sheet, or clipboard write blocked —
      // either way we don't need to surface an error.
    }
  }

  async function handleBlock() {
    if (!canWrite || blocking || isOwnPost) return;
    const token = getToken();
    if (!token) return;
    setBlocking(true);
    setOverflowOpen(false);
    try {
      await blockAgent(post.author_did, token);
      setBlocked(true);
    } catch {
      /* silent — block errors are non-critical */
    } finally {
      setBlocking(false);
    }
  }

  // Hide the whole card once the user has blocked its author
  if (blocked) return null;

  return (
    <motion.article
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: Math.min(index * 0.04, 0.3) }}
      // data-post-nav + tabIndex=-1 make this card a programmatic focus
      // target for the j/k keyboard navigation in components/layout/
      // KeyboardShortcuts.tsx — Twitter/Bluesky power-user parity. tabIndex
      // -1 keeps it out of the natural Tab order (Tab still steps through
      // the interactive controls inside) while still allowing .focus().
      // The focus-visible ring is what the user *sees* while j/k-ing.
      data-post-nav
      tabIndex={-1}
      className="group rounded-xl border border-slate-800 bg-slate-900 p-4
                 hover:border-slate-700 hover:bg-slate-900/80 transition-colors
                 focus:outline-none focus-visible:ring-2
                 focus-visible:ring-cyan-500/60 focus-visible:border-cyan-500/40
                 scroll-mt-20"
    >
      {/* Top row */}
      <div className="flex items-center justify-between mb-3">
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border"
          style={{
            color: meta.color,
            borderColor: `${meta.color}44`,
            backgroundColor: `${meta.color}12`,
          }}
        >
          <Icon className="w-3 h-3" />
          {meta.label}
        </span>
        <div className="flex items-center gap-2">
          {/* Timestamp doubles as the "open thread" affordance — Bluesky /
              Twitter / Mastodon all use this convention. Previously the card
              had NO keyboard-accessible path to /post/[id]; the action-row
              Reply button only toggles the inline thread. Wrapping <time> in
              a <Link> gives us:
                • Tab-focusable, Enter-actionable navigation to the full thread
                • `dateTime` preserved for machine-readable timestamps
                • `title` surfaces both the action and the absolute date
                • `aria-label` gives screen readers full context */}
          <Link
            href={`/post/${post.post_id}`}
            title={`Open thread · ${fullTimestamp(post.created_at)}`}
            aria-label={`Open thread, posted ${fullTimestamp(post.created_at)}`}
            className="flex items-center gap-1 text-[10px] text-slate-600 hover:text-slate-300 focus:text-slate-300 focus:outline-none transition-colors"
          >
            <Clock className="w-3 h-3" />
            <time dateTime={post.created_at}>
              {timeAgo(post.created_at)}
            </time>
          </Link>

          {/* Overflow menu — only for authenticated non-authors */}
          {canWrite && !isOwnPost && (
            <div className="relative">
              <button
                type="button"
                onClick={() => setOverflowOpen((v) => !v)}
                className="p-0.5 rounded text-slate-600 hover:text-slate-400 transition-colors
                           opacity-0 group-hover:opacity-100 focus:opacity-100"
                aria-label="More options"
              >
                <MoreHorizontal className="w-3.5 h-3.5" />
              </button>

              {overflowOpen && (
                <div
                  className="absolute right-0 top-5 z-20 min-w-[130px] rounded-lg
                             border border-slate-700 bg-slate-900 shadow-xl py-1"
                >
                  <button
                    type="button"
                    onClick={handleBlock}
                    disabled={blocking}
                    className="flex items-center gap-2 w-full px-3 py-1.5 text-xs
                               text-red-400 hover:bg-slate-800 transition-colors
                               disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    <ShieldOff className="w-3 h-3 shrink-0" />
                    {blocking ? "Blocking…" : `Block ${name}`}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Author */}
      <div className="flex items-center gap-2 mb-2">
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
          style={{
            background: `radial-gradient(circle at 35% 35%, ${meta.color}88, ${meta.color})`,
          }}
        >
          {name.slice(0, 2).toUpperCase()}
        </div>
        <div className="flex items-center gap-1.5 min-w-0">
          {/* Author name → profile link, now with the same hover-card
              preview that @mentions get inline (rich text uses
              AgentHoverCard via lib/text/richText). Bluesky / Twitter
              both surface this preview on every author reference, not
              just rich-text mentions — matching that here means a
              reader hovering any post's byline gets bio, trust badge,
              and an inline Follow toggle without leaving the feed. */}
          <AgentHoverCard
            did={post.author_did}
            href={`/agents/${encodeURIComponent(post.author_did)}`}
            className="text-sm font-medium text-slate-200 hover:text-white truncate transition-colors
                       rounded -mx-0.5 px-0.5
                       focus-visible:outline-none focus-visible:ring-2
                       focus-visible:ring-slate-500/50 focus-visible:ring-offset-2
                       focus-visible:ring-offset-slate-900"
          >
            {name}
          </AgentHoverCard>
          <TrustDot trust={trust} />
        </div>
      </div>

      {/* Repost banner — suppress title/content body when it's a plain repost
          (the source is rendered below via QuotedCard). */}
      {isRepost && (
        <p className="text-[11px] text-slate-500 mb-2 flex items-center gap-1">
          <Repeat2 className="w-3 h-3" />
          {name} reposted
        </p>
      )}

      {/* Title — hidden on plain repost (the quoted card carries the real
          content). Detail mode drops the single-line clamp so long titles
          wrap on the permalink page. */}
      {!isRepost && post.title && (
        <h3
          className={`font-semibold text-slate-100 mb-1 ${
            detail ? "text-base" : "text-sm line-clamp-1"
          }`}
        >
          {post.title}
        </h3>
      )}

      {/* Content — hidden on plain repost. renderRichText linkifies
          @mentions, #hashtags, and URLs inline. Feed mode clamps to 3
          lines; Show more inline-expands without losing scroll position
          (the timestamp link also navigates to the permalink for users
          who prefer that). Detail mode renders the full body — slightly
          larger leading too, since the permalink page is where users
          settle in to read. whitespace-pre-wrap preserves authored line
          breaks in both modes. */}
      {!isRepost && (
        <>
          <p
            ref={contentRef}
            className={`leading-relaxed whitespace-pre-wrap ${
              detail || contentExpanded
                ? "text-base text-slate-300 mb-3"
                : "text-sm text-slate-400 line-clamp-3 mb-1"
            }`}
          >
            {renderRichText(post.content)}
          </p>
          {!detail && contentOverflowed && !contentExpanded && (
            // stopPropagation so the click doesn't bubble to any parent
            // card-level handler that might navigate to the permalink —
            // the user explicitly chose "expand here, don't take me away".
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setContentExpanded(true);
              }}
              className="text-xs text-cyan-400 hover:text-cyan-300 mb-3
                         focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-cyan-500/60 rounded px-1 -ml-1"
              aria-label="Show full post content"
            >
              Show more
            </button>
          )}
        </>
      )}

      {/* Quoted post (if any) */}
      {quoted && <QuotedCard post={quoted} />}

      {/* Tags — chip row. Each chip is a sibling pair: a <Link> to the
          /tag/[name] feed plus a tiny pin/unpin <button> that toggles
          this hashtag in the user's pinned-feeds set (lib/storage/pinnedTags).
          Sibling layout (not button-inside-link) avoids the interactive-
          inside-interactive a11y violation, matching the pattern used
          for pinned-tab × buttons in LiveFeed and the ml-auto pin
          button on /tag/[name].

          The inline pin affordance composes with the f729b17 pinned-
          feeds primitive: a user reading their feed can pin #defi the
          moment they spot it on a post, without navigating to
          /tag/defi first. Bluesky-parity: their feed cards have a
          "Save feed" button on hashtag mentions; this is the same
          velocity primitive. */}
      {post.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3 mt-3">
          {post.tags.slice(0, 5).map((tag) => {
            const lower = tag.toLowerCase();
            const isPinned = pinnedTags.includes(lower);
            // At-cap UX: pinning past MAX_PINNED evicts the oldest pin
            // (per pinTag helper). Surface that in the tooltip rather
            // than letting the eviction surprise the user.
            const atCap = !isPinned && pinnedTags.length >= MAX_PINNED;
            const oldestPin = pinnedTags[0];

            const pinTitle = isPinned
              ? `Unpin #${tag} from home feed`
              : atCap
                ? `Pinning will replace your oldest pinned tag (#${oldestPin}). You can have up to ${MAX_PINNED} pinned hashtags.`
                : `Pin #${tag} as a tab on the home feed`;

            return (
              <span
                key={tag}
                className={`inline-flex items-stretch rounded overflow-hidden text-[10px] ${
                  isPinned
                    ? "bg-cyan-500/10 ring-1 ring-cyan-500/30"
                    : "bg-slate-800 hover:bg-slate-700 transition-colors"
                }`}
              >
                <Link
                  href={`/tag/${encodeURIComponent(tag)}`}
                  title={`View all #${tag} posts`}
                  className={`px-1.5 py-0.5 transition-colors
                              focus-visible:outline-none focus-visible:ring-2
                              focus-visible:ring-slate-500/50 focus-visible:ring-offset-2
                              focus-visible:ring-offset-slate-900 ${
                    isPinned
                      ? "text-cyan-300 hover:text-cyan-200"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  #{tag}
                </Link>
                <button
                  type="button"
                  onClick={() => togglePinnedTag(tag)}
                  title={pinTitle}
                  aria-label={pinTitle}
                  aria-pressed={isPinned}
                  className={`px-1 flex items-center justify-center
                              transition-colors border-l
                              focus-visible:outline-none focus-visible:ring-2
                              focus-visible:ring-cyan-500/50 focus-visible:ring-offset-2
                              focus-visible:ring-offset-slate-900 ${
                    isPinned
                      ? "border-cyan-500/30 text-cyan-300 hover:text-cyan-200 hover:bg-cyan-500/20"
                      : "border-slate-700 text-slate-500 hover:text-slate-200 hover:bg-slate-600"
                  }`}
                >
                  {isPinned ? (
                    <PinOff className="w-2.5 h-2.5" />
                  ) : (
                    <Pin className="w-2.5 h-2.5" />
                  )}
                </button>
              </span>
            );
          })}
        </div>
      )}

      {/* Action row */}
      <div className="flex items-center gap-4 text-[11px] text-slate-500 mt-2">
        <button
          type="button"
          onClick={handleLike}
          disabled={!canWrite || liking}
          className={`${ACTION_BTN_BASE} ${
            liked ? "text-pink-400" : "hover:text-slate-300"
          }`}
          title={canWrite ? "Like" : "Log in to like"}
        >
          <ThumbsUp className="w-3.5 h-3.5" />
          {likeCount}
        </button>

        {inThread ? (
          // In thread context the parent thread already auto-shows this
          // post's direct children below it, so toggling another inline
          // thread here would just duplicate the same content. Send the
          // user to this post's permalink instead — that's where the
          // composer is anchored to *this* reply, matching Bluesky's
          // "click into a reply to reply to it" pattern.
          <Link
            href={`/post/${post.post_id}`}
            className={`${ACTION_BTN_BASE} hover:text-slate-300`}
            title="Open this reply in its own thread"
          >
            <Reply className="w-3.5 h-3.5" />
            {replyCount}
          </Link>
        ) : (
          <button
            type="button"
            onClick={() => setThreadOpen((v) => !v)}
            className={`${ACTION_BTN_BASE} ${
              threadOpen ? "text-cyan-400" : "hover:text-slate-300"
            }`}
            title="Replies"
          >
            <Reply className="w-3.5 h-3.5" />
            {replyCount}
          </button>
        )}

        <button
          type="button"
          onClick={handleRepost}
          disabled={!canWrite || reposting || reposted || isRepost || isOwnPost}
          className={`${ACTION_BTN_BASE} ${
            reposted ? "text-emerald-400" : "hover:text-emerald-300"
          }`}
          title={
            isOwnPost
              ? "Can't repost your own post"
              : isRepost
                ? "This is already a repost"
                : reposted
                  ? "Reposted"
                  : canWrite
                    ? "Repost"
                    : "Log in to repost"
          }
        >
          <Repeat2 className="w-3.5 h-3.5" />
          {reposting ? "…" : reposted ? "Reposted" : "Repost"}
        </button>

        <button
          type="button"
          onClick={() => canWrite && setQuoteOpen(true)}
          disabled={!canWrite}
          className={`${ACTION_BTN_BASE} hover:text-slate-300`}
          title={canWrite ? "Quote" : "Log in to quote"}
        >
          <QuoteIcon className="w-3.5 h-3.5" />
          Quote
        </button>

        <button
          type="button"
          onClick={handleShare}
          className={`${ACTION_BTN_BASE} ${
            shared ? "text-emerald-400" : "hover:text-slate-300"
          }`}
          title={shared ? "Link copied" : "Share"}
          aria-label="Share this post"
        >
          {shared ? <Check className="w-3.5 h-3.5" /> : <Share2 className="w-3.5 h-3.5" />}
          {shared ? "Copied" : "Share"}
        </button>

        {canStartRoom && (
          <button
            type="button"
            onClick={handleStartRoom}
            disabled={!canWrite || startingRoom}
            className={`${ACTION_BTN_BASE} hover:text-cyan-300 ml-auto`}
            title={canWrite ? "Start a collaboration room" : "Log in to start a room"}
          >
            <UsersIcon className="w-3.5 h-3.5" />
            {startingRoom ? "Starting…" : "Start Room"}
          </button>
        )}

        {post.vote_count != null && (
          <span className="flex items-center gap-1 ml-auto">
            <Vote className="w-3.5 h-3.5" />
            {post.vote_count}
          </span>
        )}
      </div>

      {threadOpen && !inThread && (
        <InlineThread
          postId={post.post_id}
          onReplyPosted={() => setReplyCount((c) => c + 1)}
        />
      )}

      {quoteOpen && (
        <QuoteModal
          post={post}
          onClose={() => setQuoteOpen(false)}
          onPosted={() => setReplyCount((c) => c)}
        />
      )}
    </motion.article>
  );
});
