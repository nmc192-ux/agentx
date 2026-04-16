"use client";
import { useState, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useQueryClient } from "@tanstack/react-query";
import {
  MessageCircle, Heart, Repeat2, BarChart2, DoorOpen, Quote,
  RotateCcw, ChevronDown, ChevronUp, X, Loader2,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { likePost, createPost, createRoom, getPostReplies } from "@/lib/api";
import type { SocialPost, Post } from "@/types";
import { trustTierFromScore } from "@/types";
import { timeAgo } from "@/lib/utils";

// Accept both the legacy Post type and the richer SocialPost
type AnyPost = SocialPost | (Post & {
  like_count?:   number;
  reply_count?:  number;
  author_name?:  string | null;
  author_trust?: number | null;
  metadata?:     Record<string, unknown>;
});

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
  let hash = 0;
  for (let i = 0; i < did.length; i++) hash = ((hash << 5) - hash + did.charCodeAt(i)) | 0;
  const hue = Math.abs(hash) % 360;
  return (
    <div
      style={{
        width: size, height: size,
        background: `hsl(${hue}, 60%, 40%)`,
        borderRadius: "50%",
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "#fff", fontWeight: 700, fontSize: size * 0.4, flexShrink: 0,
      }}
    >
      {letter}
    </div>
  );
}

// Quoted post card (nested inline)
function QuotedCard({ post }: { post: AnyPost }) {
  return (
    <Link
      href={`/post/${post.post_id}`}
      onClick={e => e.stopPropagation()}
      className="
        block mt-2 px-3 py-2.5
        border border-border-primary rounded-xl
        bg-surface-secondary/30 hover:bg-surface-secondary/60
        transition-colors
      "
    >
      <div className="flex items-center gap-1.5 mb-1">
        <AgentAvatar name={post.author_name} did={post.author_did} size={18} />
        <span className="text-xs font-semibold text-text-primary">
          {post.author_name ?? post.author_did.split(":").pop()}
        </span>
        <span className="text-xs text-text-quaternary">· {timeAgo(post.created_at)}</span>
      </div>
      <p className="text-xs font-medium text-text-primary truncate">{post.title}</p>
      <p className="text-xs text-text-secondary line-clamp-2 mt-0.5 leading-snug">{post.content}</p>
    </Link>
  );
}

// Repost dropdown menu (floats over the button)
function RepostMenu({
  onClose,
  onSimpleRepost,
  onQuote,
}: {
  onClose: () => void;
  onSimpleRepost: () => void;
  onQuote: () => void;
}) {
  return (
    <div
      className="absolute bottom-full left-0 mb-1 z-30
                 bg-surface-primary border border-border-primary
                 rounded-xl shadow-lg overflow-hidden min-w-[160px]"
    >
      <button
        onClick={() => { onSimpleRepost(); onClose(); }}
        className="flex items-center gap-2.5 w-full px-4 py-2.5 text-sm
                   text-text-primary hover:bg-surface-secondary transition-colors"
      >
        <RotateCcw size={14} />
        Repost
      </button>
      <button
        onClick={() => { onQuote(); onClose(); }}
        className="flex items-center gap-2.5 w-full px-4 py-2.5 text-sm
                   text-text-primary hover:bg-surface-secondary transition-colors"
      >
        <Quote size={14} />
        Quote Post
      </button>
    </div>
  );
}

interface Props {
  post:        AnyPost;
  compact?:    boolean;
  showReply?:  boolean;
  showAuthor?: boolean;
  animate?:    boolean;
}

export function PostCard({ post, compact = false }: Props) {
  const { data: session } = useSession();
  const qc     = useQueryClient();
  const router = useRouter();

  const [liked,       setLiked]       = useState(false);
  const [likeCount,   setLikeCount]   = useState(post.like_count ?? 0);
  const [pending,     setPending]     = useState(false);
  const [showThread,  setShowThread]  = useState(false);
  const [showRepost,  setShowRepost]  = useState(false);
  const [quoteModal,  setQuoteModal]  = useState(false);
  const [roomLoading, setRoomLoading] = useState(false);

  const token = (session as any)?.accessToken as string | undefined;
  const cfg   = POST_TYPE_CONFIG[post.post_type] ?? POST_TYPE_CONFIG.UPDATE;
  const name  = post.author_name ?? post.author_did?.split(":").pop() ?? "unknown";
  const handle = post.author_did?.split(":").pop() ?? "unknown";
  const tier  = trustTierFromScore(post.author_trust ?? 0);

  const tierColors: Record<string, string> = {
    elite: "#F59E0B", trusted: "#8B5CF6", verified: "#3B82F6", unverified: "#6B7280",
  };

  const quotedPostId = post.metadata?.quoted_post_id as string | undefined;
  const isRoomable   = post.post_type === "REQUEST" || post.post_type === "TASK";

  async function handleLike(e: React.MouseEvent) {
    e.preventDefault(); e.stopPropagation();
    if (!token || pending) return;
    setPending(true);
    try {
      const res = await likePost(post.post_id, token);
      setLiked(res.liked);
      setLikeCount(res.like_count);
      qc.invalidateQueries({ queryKey: ["global-feed"] });
      qc.invalidateQueries({ queryKey: ["home-feed"] });
    } catch { /* noop */ } finally { setPending(false); }
  }

  async function handleSimpleRepost(e?: React.MouseEvent) {
    e?.preventDefault(); e?.stopPropagation();
    if (!token) return;
    try {
      await createPost(
        {
          post_type:  "UPDATE",
          title:      `↩ ${post.title.slice(0, 180)}`,
          content:    post.content.slice(0, 500),
          visibility: "PUBLIC",
          tags:       post.tags ?? [],
          metadata:   { quoted_post_id: post.post_id },
        },
        token,
      );
      qc.invalidateQueries({ queryKey: ["global-feed"] });
      qc.invalidateQueries({ queryKey: ["home-feed"] });
    } catch { /* noop */ }
  }

  async function handleStartRoom(e: React.MouseEvent) {
    e.preventDefault(); e.stopPropagation();
    if (!token || roomLoading) return;
    setRoomLoading(true);
    try {
      const room = await createRoom(
        { name: post.title.slice(0, 80), linked_post_id: post.post_id },
        token,
      );
      router.push(`/rooms/${room.room_id}`);
    } catch {
      setRoomLoading(false);
    }
  }

  const MAX_CHARS = 280;
  const contentPreview = post.content.length > MAX_CHARS
    ? post.content.slice(0, MAX_CHARS) + "…"
    : post.content;

  return (
    <>
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
              <span
                className="w-1.5 h-1.5 rounded-full shrink-0"
                style={{ background: tierColors[tier] }}
                title={tier}
              />
              <span className="text-text-tertiary text-sm">@{handle}</span>
              <span className="text-text-quaternary text-sm">·</span>
              <span className="text-text-quaternary text-sm shrink-0">{timeAgo(post.created_at)}</span>
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

            {/* Quoted post (if this is a quote-repost) */}
            {quotedPostId && (
              <QuotedCard post={{ ...post, post_id: quotedPostId }} />
            )}

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
                {/* Reply / thread toggle */}
                <button
                  onClick={e => { e.preventDefault(); e.stopPropagation(); setShowThread(v => !v); }}
                  className="flex items-center gap-1.5 hover:text-accent-info transition-colors group"
                >
                  <span className="p-1.5 rounded-full group-hover:bg-accent-info/10 transition-colors">
                    <MessageCircle size={16} />
                  </span>
                  <span className="text-xs">{post.reply_count ?? 0}</span>
                  {(post.reply_count ?? 0) > 0 && (
                    <span className="text-xs opacity-60">
                      {showThread ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                    </span>
                  )}
                </button>

                {/* Repost / quote menu */}
                <div className="relative">
                  <button
                    onClick={e => { e.preventDefault(); e.stopPropagation(); setShowRepost(v => !v); }}
                    className="flex items-center gap-1.5 hover:text-accent-success transition-colors group"
                  >
                    <span className="p-1.5 rounded-full group-hover:bg-accent-success/10 transition-colors">
                      <Repeat2 size={16} />
                    </span>
                  </button>
                  {showRepost && (
                    <RepostMenu
                      onClose={() => setShowRepost(false)}
                      onSimpleRepost={handleSimpleRepost}
                      onQuote={() => setQuoteModal(true)}
                    />
                  )}
                </div>

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

                {/* Start Room — REQUEST / TASK only */}
                {isRoomable && token && (
                  <button
                    onClick={handleStartRoom}
                    disabled={roomLoading}
                    className="flex items-center gap-1.5 hover:text-accent-primary transition-colors group ml-1 disabled:opacity-40"
                    title="Start a collaboration room for this post"
                  >
                    <span className="p-1.5 rounded-full group-hover:bg-accent-primary/10 transition-colors">
                      <DoorOpen size={16} />
                    </span>
                    <span className="text-xs hidden sm:inline">{roomLoading ? "…" : "Room"}</span>
                  </button>
                )}

                {/* Trust score */}
                <div className="flex items-center gap-1.5 ml-auto">
                  <BarChart2 size={14} />
                  <span className="text-xs">{Math.round((post.author_trust ?? 0) * 100)}%</span>
                </div>
              </div>
            )}
          </div>
        </Link>

        {/* Inline comment thread (expands below action bar) */}
        {showThread && !compact && (post.reply_count ?? 0) > 0 && (
          <InlineThread postId={post.post_id} replyCount={post.reply_count ?? 0} />
        )}
      </article>

      {/* Quote modal (portal-like, renders outside article) */}
      {quoteModal && (
        <QuoteModal post={post as SocialPost} onClose={() => setQuoteModal(false)} />
      )}
    </>
  );
}

// ── Inline thread (lazy-loaded replies) ────────────────────────────────────────

function InlineThread({ postId, replyCount }: { postId: string; replyCount: number }) {
  const { data: session } = useSession();
  const token = (session as any)?.accessToken as string | undefined;

  const { data, isLoading } = useQuery({
    queryKey: ["thread-replies", postId],
    queryFn:  () => getPostReplies(postId, { limit: 3 }, token),
    staleTime: 30_000,
  });

  const replies: SocialPost[] = data?.posts ?? [];

  return (
    <div className="mt-2 border-t border-border-primary/20 pl-4">
      {isLoading ? (
        <div className="flex items-center gap-2 py-2 text-xs text-text-tertiary">
          <Loader2 size={12} className="animate-spin" /> Loading replies…
        </div>
      ) : replies.length === 0 ? (
        <p className="py-2 text-xs text-text-tertiary italic">No replies yet.</p>
      ) : (
        <>
          {replies.map(reply => (
            <div
              key={reply.post_id}
              className="border-l-2 border-border-primary/30 ml-4 pl-0"
            >
              <PostCard post={reply} compact />
            </div>
          ))}
          {replyCount > 3 && (
            <Link
              href={`/post/${postId}`}
              onClick={e => e.stopPropagation()}
              className="block py-2 text-xs text-accent-primary hover:underline"
            >
              View all {replyCount} replies →
            </Link>
          )}
        </>
      )}
    </div>
  );
}

// ── Quote Modal ───────────────────────────────────────────────────────────────

function QuoteModal({
  post,
  onClose,
}: {
  post: SocialPost;
  onClose: () => void;
}) {
  const { data: session } = useSession();
  const qc    = useQueryClient();
  const token = (session as any)?.accessToken as string | undefined;
  const did   = (session as any)?.agentDID    as string | undefined;
  const uname = (session as any)?.displayName as string | undefined;

  const [title,   setTitle]   = useState(`Re: ${post.title.slice(0, 160)}`);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !content.trim()) return;
    setLoading(true); setError(null);
    try {
      await createPost(
        {
          post_type:  "UPDATE",
          title:      title.trim() || `Re: ${post.title}`,
          content:    content.trim(),
          visibility: "PUBLIC",
          tags:       post.tags ?? [],
          metadata:   { quoted_post_id: post.post_id },
        },
        token,
      );
      qc.invalidateQueries({ queryKey: ["global-feed"] });
      qc.invalidateQueries({ queryKey: ["home-feed"] });
      onClose();
    } catch (err: any) {
      setError(err?.message ?? "Failed to post");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-16 px-4 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg bg-surface-primary border border-border-primary rounded-2xl shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-border-primary">
          <h2 className="font-semibold text-sm text-text-primary">Quote Post</h2>
          <button onClick={onClose} className="p-1.5 rounded-full hover:bg-surface-secondary transition-colors">
            <X size={16} />
          </button>
        </div>
        <form onSubmit={submit} className="px-4 py-4">
          <div className="flex gap-3">
            {did && <AgentAvatar name={uname} did={did} />}
            <div className="flex-1 min-w-0">
              <input
                type="text"
                value={title}
                onChange={e => setTitle(e.target.value)}
                maxLength={200}
                className="w-full mb-2 bg-transparent text-text-primary text-sm font-medium placeholder:text-text-quaternary border-none outline-none"
              />
              <textarea
                value={content}
                onChange={e => setContent(e.target.value)}
                placeholder="Add your commentary…"
                rows={3}
                autoFocus
                className="w-full bg-transparent text-text-primary text-sm leading-relaxed placeholder:text-text-quaternary border-none outline-none resize-none"
              />
              {/* quoted post preview */}
              <QuotedCard post={post} />
              {error && <p className="text-accent-error text-xs mt-2">{error}</p>}
              <div className="flex justify-end mt-4">
                <button
                  type="submit"
                  disabled={!token || !content.trim() || loading}
                  className="flex items-center gap-2 bg-accent-primary hover:bg-accent-primary/90 text-white font-semibold text-sm px-5 py-1.5 rounded-full transition-all active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {loading && <Loader2 size={14} className="animate-spin" />}
                  Quote Post
                </button>
              </div>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

// Re-export AgentAvatar for use in other components
export { AgentAvatar };
