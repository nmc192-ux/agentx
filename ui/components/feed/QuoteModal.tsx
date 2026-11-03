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
import { hasBody } from "@/lib/composerMedia";
import { ComposerImageButton, ComposerImageList, useComposerImages } from "./ComposerImages";
import { useEscapeKey } from "@/lib/hooks/useEscapeKey";

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
  // Layer 1 S4-10a2: images, shown only while the API has uploads on.
  const images = useComposerImages();
  const canSubmit = hasBody(content, images.items) && !loading && !images.altError;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const token = getToken();
    if (!token || !canSubmit) return;
    setLoading(true);
    setError(null);
    try {
      let mediaIds: string[] = [];
      if (images.items.length > 0) {
        const uploaded = await images.upload(token);
        if (!uploaded) {
          setError("An image could not be uploaded; see the message under it.");
          return;
        }
        mediaIds = uploaded;
      }
      const created = await createPost(
        {
          post_type: "UPDATE",
          title: title.trim() || `Re: ${post.title ?? ""}`.trim() || "Quote",
          content: content.trim(),
          visibility: "PUBLIC",
          quote_post_id: post.post_id,
          ...(mediaIds.length > 0 ? { media_ids: mediaIds } : {}),
        },
        token,
      );
      onPosted?.(created as SocialPost);
      images.clear();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to post");
    } finally {
      setLoading(false);
    }
  }

  useEscapeKey(onClose);

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-start justify-center pt-16 px-4
                 bg-black/60 backdrop-blur-sm"
      onClick={(e) => { e.stopPropagation(); if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`quote-${post.post_id}`}
        className="w-full max-w-lg bg-slate-900 border border-slate-700 rounded-2xl
                   shadow-2xl overflow-hidden"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <h2 id={`quote-${post.post_id}`} className="font-semibold text-sm text-slate-100">Quote Post</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
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
            aria-label="Title"
            className="w-full mb-2 bg-transparent text-slate-100 text-sm font-medium
                       placeholder:text-slate-600 outline-none"
          />
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Add your commentary…"
            aria-label="Your commentary"
            rows={3}
            // Focus moves into the dialog when it opens (WAI-ARIA dialog pattern).
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
            className="w-full bg-transparent text-slate-100 text-sm leading-relaxed
                       placeholder:text-slate-600 outline-none resize-none"
          />

          <ComposerImageList images={images} disabled={loading} />

          <QuotedCard post={preview(post)} />

          {error && <p className="text-red-400 text-xs mt-2">{error}</p>}

          <div className="flex items-center justify-between mt-4">
            <ComposerImageButton images={images} disabled={loading} />
            <button
              type="submit"
              disabled={!canSubmit}
              className="ml-auto flex items-center gap-2 bg-cyan-600 hover:bg-cyan-500 text-white
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
