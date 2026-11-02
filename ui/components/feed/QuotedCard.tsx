"use client";
import Link from "next/link";
import type { QuoteEmbedShape } from "@/lib/postCard";
import { cardAuthor, shortTimeAgo } from "@/lib/postCard";

/**
 * Compact inline rendering of a quoted post — used inside QuoteModal and
 * inside PostCard for the server's `quoted_post` embed (Layer 1 S3-8b).
 * Plain text only: the quoted text is a React text node, never HTML.
 */
export function QuotedCard({ post }: { post: QuoteEmbedShape }) {
  const author = cardAuthor(post);
  const name = author.name;
  return (
    <Link
      href={`/post/${post.post_id}`}
      onClick={(e) => e.stopPropagation()}
      title="View quoted post"
      aria-label={`View quoted post by ${name}`}
      data-quoted-post
      className="block mt-2 px-3 py-2.5 border border-slate-800 rounded-xl
                 bg-slate-800/40 hover:bg-slate-800/70 transition-colors
                 focus-visible:outline-none focus-visible:ring-2
                 focus-visible:ring-slate-500/50 focus-visible:ring-offset-2
                 focus-visible:ring-offset-slate-900"
    >
      <div className="flex items-center gap-1.5 mb-1">
        <div className="w-4 h-4 rounded-full bg-gradient-to-br from-cyan-500 to-blue-500 text-[9px] font-bold text-white flex items-center justify-center">
          {name.slice(0, 1).toUpperCase()}
        </div>
        <span className="text-xs font-semibold text-slate-200">{name}</span>
        {author.handle && <span className="text-xs text-slate-500">{author.handle}</span>}
        {post.created_at && (
          <span className="text-xs text-slate-500">· {shortTimeAgo(post.created_at)}</span>
        )}
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

/** The quoted post is gone, hidden, private to the reader, or across a block. */
export function UnavailableQuote() {
  return (
    <div
      data-quoted-post="unavailable"
      className="mt-2 px-3 py-2.5 border border-slate-800 rounded-xl bg-slate-800/20
                 text-xs text-slate-500"
    >
      This post is unavailable
    </div>
  );
}
