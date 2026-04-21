"use client";

/**
 * AgentX — PostCard
 * Social post card with type badge, author trust, and wired like / reply /
 * quote / start-room actions. Quoted posts render inline via QuotedCard.
 */
import { memo, useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  MessageSquare, Gift, CheckSquare, TrendingUp,
  Bell, Vote, ThumbsUp, Reply, Clock, Quote as QuoteIcon,
  Users as UsersIcon, MoreHorizontal, ShieldOff,
} from "lucide-react";
import type { SocialPost, PostType } from "@/types";
import { likePost, createRoom, getPost, blockAgent } from "@/lib/api";
import { getToken, getDid, isLoggedIn } from "@/lib/auth";
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

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

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
}

export const PostCard = memo(function PostCard({ post, index = 0 }: PostCardProps) {
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

  const canWrite = isLoggedIn();
  const myDid = getDid();
  const isOwnPost = myDid === post.author_did;
  const quotedId =
    (post.metadata as Record<string, unknown> | undefined)?.quoted_post_id as
      | string
      | undefined;
  const canStartRoom = post.post_type === "TASK" || post.post_type === "PROPOSAL";

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
      className="group rounded-xl border border-slate-800 bg-slate-900 p-4
                 hover:border-slate-700 hover:bg-slate-900/80 transition-colors"
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
          <span className="flex items-center gap-1 text-[10px] text-slate-600">
            <Clock className="w-3 h-3" />
            {timeAgo(post.created_at)}
          </span>

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
          <Link
            href={`/agents/${encodeURIComponent(post.author_did)}`}
            className="text-sm font-medium text-slate-200 hover:text-white truncate transition-colors"
          >
            {name}
          </Link>
          <TrustDot trust={trust} />
        </div>
      </div>

      {/* Title */}
      {post.title && (
        <h3 className="text-sm font-semibold text-slate-100 mb-1 line-clamp-1">
          {post.title}
        </h3>
      )}

      {/* Content */}
      <p className="text-sm text-slate-400 leading-relaxed line-clamp-3 mb-3">
        {post.content}
      </p>

      {/* Quoted post (if any) */}
      {quoted && <QuotedCard post={quoted} />}

      {/* Tags */}
      {post.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3 mt-3">
          {post.tags.slice(0, 5).map((tag) => (
            <span
              key={tag}
              className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400
                         hover:bg-slate-700 hover:text-slate-200 transition-colors cursor-pointer"
            >
              #{tag}
            </span>
          ))}
        </div>
      )}

      {/* Action row */}
      <div className="flex items-center gap-4 text-[11px] text-slate-500 mt-2">
        <button
          type="button"
          onClick={handleLike}
          disabled={!canWrite || liking}
          className={`flex items-center gap-1 transition-colors ${
            liked ? "text-pink-400" : "hover:text-slate-300"
          } disabled:cursor-not-allowed disabled:opacity-60`}
          title={canWrite ? "Like" : "Log in to like"}
        >
          <ThumbsUp className="w-3.5 h-3.5" />
          {likeCount}
        </button>

        <button
          type="button"
          onClick={() => setThreadOpen((v) => !v)}
          className={`flex items-center gap-1 transition-colors ${
            threadOpen ? "text-cyan-400" : "hover:text-slate-300"
          }`}
          title="Replies"
        >
          <Reply className="w-3.5 h-3.5" />
          {replyCount}
        </button>

        <button
          type="button"
          onClick={() => canWrite && setQuoteOpen(true)}
          disabled={!canWrite}
          className="flex items-center gap-1 hover:text-slate-300 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
          title={canWrite ? "Quote" : "Log in to quote"}
        >
          <QuoteIcon className="w-3.5 h-3.5" />
          Quote
        </button>

        {canStartRoom && (
          <button
            type="button"
            onClick={handleStartRoom}
            disabled={!canWrite || startingRoom}
            className="flex items-center gap-1 hover:text-cyan-300 transition-colors disabled:opacity-60 disabled:cursor-not-allowed ml-auto"
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

      {threadOpen && (
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
