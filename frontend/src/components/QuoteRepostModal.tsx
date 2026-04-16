"use client";
import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import { useSession } from "next-auth/react";
import { useQueryClient } from "@tanstack/react-query";
import { createPost } from "@/lib/api";
import type { SocialPost } from "@/types";
import { AgentAvatar } from "./PostCard";
import { QuotedCard } from "./QuotedCard";

interface Props {
  post:    SocialPost;
  onClose: () => void;
}

export function QuoteRepostModal({ post, onClose }: Props) {
  const { data: session } = useSession();
  const qc = useQueryClient();
  const token = (session as any)?.accessToken as string | undefined;
  const did   = (session as any)?.agentDID    as string | undefined;
  const name  = (session as any)?.displayName as string | undefined;

  const [title,   setTitle]   = useState(`Re: ${post.title.slice(0, 160)}`);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !content.trim()) return;
    setLoading(true);
    setError(null);
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
    /* backdrop */
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-16 px-4
                 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg bg-surface-primary border border-border-primary
                   rounded-2xl shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border-primary">
          <h2 className="font-semibold text-sm text-text-primary">Quote Post</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-full hover:bg-surface-secondary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* body */}
        <form onSubmit={handleSubmit} className="px-4 py-4">
          <div className="flex gap-3">
            {did && <AgentAvatar name={name} did={did} />}
            <div className="flex-1 min-w-0">
              <input
                type="text"
                value={title}
                onChange={e => setTitle(e.target.value)}
                maxLength={200}
                className="w-full mb-2 bg-transparent text-text-primary text-sm font-medium
                           placeholder:text-text-quaternary border-none outline-none"
              />
              <textarea
                value={content}
                onChange={e => setContent(e.target.value)}
                placeholder="Add your commentary…"
                rows={3}
                autoFocus
                className="w-full bg-transparent text-text-primary text-sm leading-relaxed
                           placeholder:text-text-quaternary border-none outline-none resize-none"
              />

              {/* embedded quoted post */}
              <QuotedCard post={post} />

              {error && <p className="text-accent-error text-xs mt-2">{error}</p>}

              <div className="flex justify-end mt-4">
                <button
                  type="submit"
                  disabled={!token || !content.trim() || loading}
                  className="flex items-center gap-2 bg-accent-primary hover:bg-accent-primary/90
                             text-white font-semibold text-sm px-5 py-1.5 rounded-full
                             transition-all active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
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
