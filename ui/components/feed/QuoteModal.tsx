"use client";

/**
 * AgentX — Quote Post Modal
 * Wraps a QuotedCard and composer that posts an UPDATE with
 * `quote_post_id` set (Layer 1 S3-8b). The server checks the original
 * (readable, not across a block) and embeds it as `quoted_post`.
 */
import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import { createPost } from "@/lib/api";
import { getToken } from "@/lib/auth";
import type { SocialPost } from "@/types";
import { QuotedCard } from "./QuotedCard";

/** The original as the quote composer previews it. */
function preview(post: SocialPost) {
  return {
    post_id: post.post_id,
    author_did: post.author_did,
    author_handle: post.author_handle ?? null,
    author_name: post.author_name,
    title: post.title,
    content: post.content,
    created_at: post.created_at,
  };
}

interface Props {
  post: SocialPost;
  onClose: () => void;
  onPosted?: (post: SocialPost) => void;
}

export function QuoteModal({ post, onClose, onPosted }: Props) {
  const [title, setTitle] = useState(`Re: ${(post.title ?? "").slice(0, 160)}`);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const token = getToken();
    if (!token || !content.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const created = await createPost(
        {
          post_type: "UPDATE",
          title: title.trim() || `Re: ${post.title ?? ""}`.trim() || "Quote",
          content: content.trim(),
          visibility: "PUBLIC",
          quote_post_id: post.post_id,
        },
        token,
      );
      onPosted?.(created as SocialPost);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to post");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-16 px-4
                 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg bg-slate-900 border border-slate-700 rounded-2xl
                   shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <h2 className="font-semibold text-sm text-slate-100">Quote Post</h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-full hover:bg-slate-800 transition-colors text-slate-400"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-4 py-4">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            className="w-full mb-2 bg-transparent text-slate-100 text-sm font-medium
                       placeholder:text-slate-600 outline-none"
          />
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Add your commentary…"
            rows={3}
            autoFocus
            className="w-full bg-transparent text-slate-100 text-sm leading-relaxed
                       placeholder:text-slate-600 outline-none resize-none"
          />

          <QuotedCard post={preview(post)} />

          {error && <p className="text-red-400 text-xs mt-2">{error}</p>}

          <div className="flex justify-end mt-4">
            <button
              type="submit"
              disabled={!content.trim() || loading}
              className="flex items-center gap-2 bg-cyan-600 hover:bg-cyan-500 text-white
                         font-semibold text-sm px-5 py-1.5 rounded-full transition-all
                         active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Quote Post
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
