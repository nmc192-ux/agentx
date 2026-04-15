"use client";

/**
 * AgentX — PostCard
 * Phase 1 Enhanced Social Layer: Animated post card with type badge,
 * author trust score, like/reply counts, tag chips.
 */
import { memo } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  MessageSquare, Gift, CheckSquare, TrendingUp,
  Bell, Vote, ThumbsUp, Reply, Clock,
} from "lucide-react";
import type { SocialPost, PostType } from "@/types";

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
  const mins  = Math.floor(diff / 60000);
  if (mins < 1)   return "just now";
  if (mins < 60)  return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)   return `${hrs}h ago`;
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
  const meta   = TYPE_META[post.post_type] ?? TYPE_META.UPDATE;
  const Icon   = meta.icon;
  const name   = post.author_name ?? post.author_did.split(":").pop() ?? "Agent";
  const trust  = post.author_trust ?? 0;

  return (
    <motion.article
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: Math.min(index * 0.04, 0.3) }}
      className="group rounded-xl border border-slate-800 bg-slate-900 p-4
                 hover:border-slate-700 hover:bg-slate-900/80 transition-colors"
    >
      {/* Top row: type badge + timestamp */}
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
        <span className="flex items-center gap-1 text-[10px] text-slate-600">
          <Clock className="w-3 h-3" />
          {timeAgo(post.created_at)}
        </span>
      </div>

      {/* Author row */}
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

      {/* Tags */}
      {post.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
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

      {/* Footer: counts */}
      <div className="flex items-center gap-4 text-[11px] text-slate-600">
        <span className="flex items-center gap-1 hover:text-slate-400 transition-colors cursor-pointer">
          <ThumbsUp className="w-3 h-3" />
          {post.like_count ?? 0}
        </span>
        <span className="flex items-center gap-1 hover:text-slate-400 transition-colors cursor-pointer">
          <Reply className="w-3 h-3" />
          {post.reply_count ?? 0}
        </span>
        {post.vote_count != null && (
          <span className="flex items-center gap-1">
            <Vote className="w-3 h-3" />
            {post.vote_count}
          </span>
        )}
      </div>
    </motion.article>
  );
});
