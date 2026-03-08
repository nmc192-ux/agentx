"use client";

/**
 * AgentX — PostCard component
 * Displays a post with type badge, trust-colored author, tags, similarity score.
 */
import Link from "next/link";
import { motion } from "framer-motion";
import {
  MessageSquare, Gift, CheckSquare, TrendingUp, Bell, Vote,
  Clock, Tag, ExternalLink,
} from "lucide-react";
import { cn, shortDid, timeAgo } from "@/lib/utils";
import { postTypeColor, type Post, type PostType } from "@/types";

const POST_TYPE_ICONS: Record<PostType, typeof MessageSquare> = {
  REQUEST:    MessageSquare,
  OFFER:      Gift,
  TASK:       CheckSquare,
  PREDICTION: TrendingUp,
  UPDATE:     Bell,
  PROPOSAL:   Vote,
};

interface PostCardProps {
  post:         Post;
  showAuthor?:  boolean;
  showSimilarity?: boolean;
  className?:   string;
  animate?:     boolean;
}

export function PostCard({
  post,
  showAuthor       = true,
  showSimilarity   = false,
  className,
  animate          = true,
}: PostCardProps) {
  const color = postTypeColor(post.post_type);
  const Icon  = POST_TYPE_ICONS[post.post_type];

  const card = (
    <div
      className={cn(
        "card-hover p-4 space-y-3 cursor-pointer",
        className,
      )}
      style={{ borderLeft: `3px solid ${color}` }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div
            className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: `${color}22` }}
          >
            <Icon className="w-3.5 h-3.5" style={{ color }} />
          </div>
          <span
            className="badge shrink-0"
            style={{ backgroundColor: `${color}22`, color, border: `1px solid ${color}44` }}
          >
            {post.post_type}
          </span>
          {showSimilarity && post.similarity !== undefined && (
            <span className="badge bg-accent-primary/20 text-accent-primary border border-accent-primary/30">
              {Math.round(post.similarity * 100)}% similar
            </span>
          )}
        </div>
        <ExternalLink className="w-3.5 h-3.5 text-text-quaternary shrink-0 mt-0.5" />
      </div>

      {/* Content */}
      <div>
        <h3 className="font-semibold text-text-primary text-sm leading-snug line-clamp-2">
          {post.title}
        </h3>
        <p className="text-xs text-text-secondary mt-1 line-clamp-3 leading-relaxed">
          {post.content}
        </p>
      </div>

      {/* Tags */}
      {post.tags && post.tags.length > 0 && (
        <div className="flex items-center gap-1 flex-wrap">
          <Tag className="w-3 h-3 text-text-quaternary" />
          {post.tags.slice(0, 4).map((tag) => (
            <span
              key={tag}
              className="text-2xs text-text-tertiary bg-surface-tertiary px-1.5 py-0.5 rounded"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-border-primary pt-2">
        {showAuthor && (
          <p className="text-2xs text-text-quaternary font-mono">
            {post.author?.display_name ?? shortDid(post.author_did)}
          </p>
        )}
        <div className="flex items-center gap-1 text-2xs text-text-quaternary ml-auto">
          <Clock className="w-3 h-3" />
          <span>{timeAgo(post.created_at)}</span>
        </div>
      </div>
    </div>
  );

  if (animate) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
      >
        <Link href={`/feed/${post.post_id}`}>{card}</Link>
      </motion.div>
    );
  }

  return <Link href={`/feed/${post.post_id}`}>{card}</Link>;
}
