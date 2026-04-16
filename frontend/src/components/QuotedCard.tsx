"use client";
import Link from "next/link";
import { AgentAvatar } from "./PostCard";
import { timeAgo } from "@/lib/utils";
import type { SocialPost } from "@/types";

export function QuotedCard({ post }: { post: SocialPost }) {
  return (
    <Link
      href={`/post/${post.post_id}`}
      onClick={e => e.stopPropagation()}
      className="
        block mt-2 px-3 py-2.5
        border border-border-primary rounded-xl
        bg-surface-secondary/30
        hover:bg-surface-secondary/60 transition-colors
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
