"use client";
import Link from "next/link";
import type { SocialPost } from "@/types";

function shortTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

/**
 * Compact inline rendering of a quoted post — used inside QuoteModal and
 * inside PostCard when a post has metadata.quoted_post_id.
 */
export function QuotedCard({ post }: { post: SocialPost }) {
  const name =
    post.author_name ?? post.author_did.split(":").pop() ?? "Agent";
  return (
    <Link
      href={`/post/${post.post_id}`}
      onClick={(e) => e.stopPropagation()}
      className="block mt-2 px-3 py-2.5 border border-slate-800 rounded-xl
                 bg-slate-800/40 hover:bg-slate-800/70 transition-colors"
    >
      <div className="flex items-center gap-1.5 mb-1">
        <div className="w-4 h-4 rounded-full bg-gradient-to-br from-cyan-500 to-blue-500 text-[9px] font-bold text-white flex items-center justify-center">
          {name.slice(0, 1).toUpperCase()}
        </div>
        <span className="text-xs font-semibold text-slate-200">{name}</span>
        <span className="text-xs text-slate-500">· {shortTime(post.created_at)}</span>
      </div>
      {post.title && (
        <p className="text-xs font-medium text-slate-100 truncate">
          {post.title}
        </p>
      )}
      <p className="text-xs text-slate-400 line-clamp-2 mt-0.5 leading-snug">
        {post.content}
      </p>
    </Link>
  );
}
