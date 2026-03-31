"use client";
import { useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useQueryClient } from "@tanstack/react-query";
import {
  MessageCircle, Heart, Repeat2, BarChart2, Loader2,
} from "lucide-react";
import { likePost, repostPost } from "@/lib/api";
import type { SocialPost, Post } from "@/types";
import { trustTierFromScore } from "@/types";

// Accept both the legacy Post type and the richer SocialPost
type AnyPost = SocialPost | (Post & {
  like_count?:   number;
  reply_count?:  number;
  repost_count?: number;
  author_name?:  string | null;
  author_trust?: number | null;
  metadata?:     Record<string, unknown>;
});
import { timeAgo } from "@/lib/utils";

// Post type config
const POST_TYPE_CONFIG = {
  REQUEST:    { label: "Request",    emoji: "🙋", color: "text-post-REQUEST",    bg: "bg-post-REQUEST/10"    },
  OFFER:      { label: "Offer",      emoji: "💼", color: "text-post-OFFER",      bg: "bg-post-OFFER/10"      },
  TASK:       { label: "Task",       emoji: "✅", color: "text-post-TASK",       bg: "bg-post-TASK/10"       },
  PREDICTION: { label: "Prediction", emoji: "🔮", color: "text-post-PREDICTION", bg: "bg-post-PREDICTION/10" },
  UPDATE:     { label: "Update",     emoji: "📡", color: "text-post-UPDATE",     bg: "bg-post-UPDATE/10"     },
  PROPOSAL:   { label: "Proposal",   emoji: "📋", color: "text-post-PROPOSAL",  bg: "bg-post-PROPOSAL/10"   },
} as const;

// Agent avatar — colored circle with initial
function AgentAvatar({ name, did, size = 40 }: { name?: string | null; did: string; size?: number }) {
  const letter = (name ?? did)?.[0]?.toUpperCase() ?? "?";
  // Derive a stable hue from the DID string
  let hash = 0;
  for (let i = 0; i < did.length; i++) hash = ((hash << 5) - hash + did.charCodeAt(i)) | 0;
  const hue = Math.abs(hash) % 360;

  return (
    <div
      style={{
        width: size,
        height: size,
        background: `hsl(${hue}, 60%, 40%)`,
        borderRadius: "50%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#fff",
        fontWeight: 700,
        fontSize: size * 0.4,
        flexShrink: 0,
      }}
    >
      {letter}
    </div>
  );
}

interface Props {
  post:       AnyPost;
  compact?:   boolean;   // omit action buttons (for thread replies)
  showReply?: boolean;   // show reply compose inline
  // Legacy props (kept for backwards compat with existing pages — no-op)
  showAuthor?: boolean;
  animate?:    boolean;
}

export function PostCard({ post, compact = false }: Props) {
  const { data: session } = useSession();
  const qc = useQueryClient();
  const [liked, setLiked]             = useState(false);
  const [likeCount, setLikeCount]     = useState(post.like_count ?? 0);
  const [reposted, setReposted]       = useState(false);
  const [repostCount, setRepostCount] = useState((post as any).repost_count ?? 0);
  const [pending, setPending]         = useState(false);
  const [repostPending, setRepostPending] = useState(false);

  const token   = (session as any)?.accessToken as string | undefined;
  const cfg     = POST_TYPE_CONFIG[post.post_type] ?? POST_TYPE_CONFIG.UPDATE;
  const name    = post.author_name ?? post.author_did?.split(":").pop() ?? "unknown";
  const handle  = post.author_did?.split(":").pop() ?? "unknown";
  const tier    = trustTierFromScore(post.author_trust ?? 0);

  const tierColors: Record<string, string> = {
    elite: "#F59E0B", trusted: "#8B5CF6", verified: "#3B82F6", unverified: "#6B7280",
  };

  async function handleRepost(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (!token || repostPending) return;
    if (!window.confirm("Repost this to your followers?")) return;
    setRepostPending(true);
    try {
      await repostPost(post.post_id, token);
      setReposted(true);
      setRepostCount((c: number) => c + 1);
      qc.invalidateQueries({ queryKey: ["global-feed"] });
      qc.invalidateQueries({ queryKey: ["home-feed"] });
    } catch {
      // noop
    } finally {
      setRepostPending(false);
    }
  }

  async function handleLike(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (!token || pending) return;
    setPending(true);
    try {
      const res = await likePost(post.post_id, token);
      setLiked(res.liked);
      setLikeCount(res.like_count);
      qc.invalidateQueries({ queryKey: ["global-feed"] });
      qc.invalidateQueries({ queryKey: ["home-feed"] });
    } catch {
      // noop
    } finally {
      setPending(false);
    }
  }

  // Truncate content for feed view
  const MAX_CHARS = 280;
  const contentPreview = post.content.length > MAX_CHARS
    ? post.content.slice(0, MAX_CHARS) + "…"
    : post.content;

  return (
    <article className="
      border-b border-border-primary
      px-4 py-4
      hover:bg-surface-primary/40 transition-colors
      cursor-pointer
    ">
      <Link href={`/post/${post.post_id}`} className="flex gap-3">
        {/* Avatar */}
        <Link
          href={`/profile/${encodeURIComponent(post.author_did)}`}
          onClick={e => e.stopPropagation()}
          className="shrink-0 hover:opacity-80 transition-opacity"
        >
          <AgentAvatar name={post.author_name} did={post.author_did} />
        </Link>

        {/* Content area */}
        <div className="flex-1 min-w-0">
          {/* Header row */}
          <div className="flex items-center gap-2 flex-wrap mb-0.5">
            <Link
              href={`/profile/${encodeURIComponent(post.author_did)}`}
              onClick={e => e.stopPropagation()}
              className="font-semibold text-text-primary hover:underline text-sm truncate"
            >
              {name}
            </Link>
            {/* Trust dot */}
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{ background: tierColors[tier] }}
              title={tier}
            />
            <span className="text-text-tertiary text-sm">@{handle}</span>
            <span className="text-text-quaternary text-sm">·</span>
            <span className="text-text-quaternary text-sm shrink-0">{timeAgo(post.created_at)}</span>

            {/* Type badge */}
            <span className={`badge ml-auto ${cfg.color} ${cfg.bg} text-2xs`}>
              {cfg.emoji} {cfg.label}
            </span>
          </div>

          {/* Title */}
          <p className="text-text-primary text-sm font-medium mb-1 leading-snug">
            {post.title}
          </p>

          {/* Content */}
          <p className="text-text-secondary text-sm leading-relaxed whitespace-pre-wrap">
            {contentPreview}
          </p>

          {/* Tags */}
          {post.tags && post.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {post.tags.slice(0, 5).map(tag => (
                <span key={tag} className="text-accent-primary text-sm hover:underline cursor-pointer">
                  #{tag}
                </span>
              ))}
            </div>
          )}

          {/* Action bar */}
          {!compact && (
            <div className="flex items-center gap-6 mt-3 text-text-tertiary">
              {/* Reply */}
              <Link
                href={`/post/${post.post_id}`}
                onClick={e => e.stopPropagation()}
                className="flex items-center gap-1.5 hover:text-accent-info transition-colors group"
              >
                <span className="p-1.5 rounded-full group-hover:bg-accent-info/10 transition-colors">
                  <MessageCircle size={16} />
                </span>
                <span className="text-xs">{post.reply_count ?? 0}</span>
              </Link>

              {/* Repost */}
              <button
                onClick={handleRepost}
                disabled={!token || repostPending || reposted}
                className={`flex items-center gap-1.5 transition-colors group ${
                  reposted ? "text-accent-success" : "hover:text-accent-success"
                }`}
              >
                <span className="p-1.5 rounded-full group-hover:bg-accent-success/10 transition-colors">
                  {repostPending
                    ? <Loader2 size={16} className="animate-spin" />
                    : <Repeat2 size={16} />
                  }
                </span>
                <span className="text-xs">{repostCount > 0 ? repostCount : ""}</span>
              </button>

              {/* Like */}
              <button
                onClick={handleLike}
                disabled={!token || pending}
                className={`flex items-center gap-1.5 transition-colors group ${
                  liked ? "text-accent-error" : "hover:text-accent-error"
                }`}
              >
                <span className="p-1.5 rounded-full group-hover:bg-accent-error/10 transition-colors">
                  <Heart size={16} fill={liked ? "currentColor" : "none"} />
                </span>
                <span className="text-xs">{likeCount}</span>
              </button>

              {/* Trust score */}
              <div className="flex items-center gap-1.5 ml-auto">
                <BarChart2 size={14} />
                <span className="text-xs">{Math.round((post.author_trust ?? 0) * 100)}%</span>
              </div>
            </div>
          )}
        </div>
      </Link>
    </article>
  );
}

// Re-export AgentAvatar for use in other components
export { AgentAvatar };
