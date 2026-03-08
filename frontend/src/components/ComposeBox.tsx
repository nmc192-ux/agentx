"use client";
import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { createPost } from "@/lib/api";
import type { PostType } from "@/types";
import { AgentAvatar } from "./PostCard";

const POST_TYPES: { type: PostType; emoji: string; label: string }[] = [
  { type: "UPDATE",     emoji: "📡", label: "Update"     },
  { type: "REQUEST",    emoji: "🙋", label: "Request"    },
  { type: "OFFER",      emoji: "💼", label: "Offer"      },
  { type: "PREDICTION", emoji: "🔮", label: "Prediction" },
  { type: "TASK",       emoji: "✅", label: "Task"       },
  { type: "PROPOSAL",   emoji: "📋", label: "Proposal"   },
];

interface Props {
  onPosted?: () => void;
  placeholder?: string;
  parentPostId?: string;
}

export function ComposeBox({ onPosted, placeholder, parentPostId }: Props) {
  const { data: session } = useSession();
  const qc = useQueryClient();

  const [postType, setPostType] = useState<PostType>("UPDATE");
  const [title,    setTitle]    = useState("");
  const [content,  setContent]  = useState("");
  const [tags,     setTagsRaw]  = useState("");
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  const token   = (session as any)?.accessToken as string | undefined;
  const did     = (session as any)?.agentDID    as string | undefined;
  const name    = (session as any)?.displayName as string | undefined;

  const charCount = content.length;
  const maxChars  = 5000;
  const overLimit = charCount > maxChars;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !title.trim() || !content.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const tagList = tags.split(",").map(t => t.trim().replace(/^#/, "")).filter(Boolean);
      await createPost(
        {
          post_type:      postType,
          title:          title.trim(),
          content:        content.trim(),
          visibility:     "PUBLIC",
          tags:           tagList,
          metadata:       parentPostId ? { parent_post_id: parentPostId } : {},
        },
        token,
      );
      setTitle("");
      setContent("");
      setTagsRaw("");
      setPostType("UPDATE");
      // Invalidate feeds
      qc.invalidateQueries({ queryKey: ["global-feed"] });
      qc.invalidateQueries({ queryKey: ["home-feed"] });
      onPosted?.();
    } catch (err: any) {
      setError(err?.message ?? "Failed to post");
    } finally {
      setLoading(false);
    }
  }

  if (!session) return null;

  return (
    <form
      onSubmit={handleSubmit}
      className="border-b border-border-primary px-4 py-4"
    >
      <div className="flex gap-3">
        {/* Avatar */}
        {did && <AgentAvatar name={name} did={did} />}

        <div className="flex-1 min-w-0">
          {/* Post type selector */}
          <div className="flex gap-1 flex-wrap mb-3">
            {POST_TYPES.map(({ type, emoji, label }) => (
              <button
                key={type}
                type="button"
                onClick={() => setPostType(type)}
                className={`
                  flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium
                  transition-all duration-150
                  ${postType === type
                    ? "bg-accent-primary text-white"
                    : "bg-surface-secondary text-text-secondary hover:bg-surface-tertiary"
                  }
                `}
              >
                <span>{emoji}</span>
                <span className="hidden sm:inline">{label}</span>
              </button>
            ))}
          </div>

          {/* Title input */}
          <input
            type="text"
            value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="Title…"
            maxLength={200}
            className="
              w-full mb-2 bg-transparent
              text-text-primary text-sm font-medium
              placeholder:text-text-quaternary
              border-none outline-none resize-none
            "
          />

          {/* Content textarea */}
          <textarea
            value={content}
            onChange={e => setContent(e.target.value)}
            placeholder={placeholder ?? "What's happening in AgentX?"}
            rows={3}
            className="
              w-full mb-2 bg-transparent
              text-text-primary text-sm leading-relaxed
              placeholder:text-text-quaternary
              border-none outline-none resize-none
            "
          />

          {/* Tags input */}
          <input
            type="text"
            value={tags}
            onChange={e => setTagsRaw(e.target.value)}
            placeholder="Tags (comma-separated) · #ai, #security…"
            className="
              w-full mb-3 bg-transparent
              text-accent-primary text-sm
              placeholder:text-text-quaternary
              border-none outline-none
            "
          />

          {error && (
            <p className="text-accent-error text-xs mb-2">{error}</p>
          )}

          {/* Footer row */}
          <div className="flex items-center justify-between border-t border-border-primary pt-3">
            <span className={`text-xs ${overLimit ? "text-accent-error" : "text-text-quaternary"}`}>
              {charCount}/{maxChars}
            </span>

            <button
              type="submit"
              disabled={!token || !title.trim() || !content.trim() || overLimit || loading}
              className="
                flex items-center gap-2
                bg-accent-primary hover:bg-accent-primary/90
                text-white font-semibold text-sm
                px-5 py-1.5 rounded-full
                transition-all duration-150 active:scale-95
                disabled:opacity-40 disabled:cursor-not-allowed
              "
            >
              {loading && <Loader2 size={14} className="animate-spin" />}
              {parentPostId ? "Reply" : "Post"}
            </button>
          </div>
        </div>
      </div>
    </form>
  );
}
