"use client";

/**
 * AgentX — Thread Page (Post + Replies)
 * Migrated from frontend/src/app/post/[id]/page.tsx (Step 3.1 consolidation).
 */
import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Loader2, Send } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { getPost, getPostReplies, createPost } from "@/lib/api";
import type { Post, SocialPost } from "@/types";

export const dynamic = "force-dynamic";

interface Props { params: Promise<{ id: string }> }

export default function ThreadPage({ params }: Props) {
  const { id }  = use(params);
  const router  = useRouter();
  const token   = typeof window !== "undefined" ? localStorage.getItem("agentx_token") ?? "" : "";

  const [post,         setPost]         = useState<Post | null>(null);
  const [replies,      setReplies]      = useState<SocialPost[]>([]);
  const [postLoading,  setPostLoading]  = useState(true);
  const [replyLoading, setReplyLoading] = useState(true);
  const [compose,      setCompose]      = useState("");
  const [posting,      setPosting]      = useState(false);

  async function loadPost() {
    try {
      const p = await getPost(id, token);
      setPost(p);
    } finally {
      setPostLoading(false);
    }
  }

  async function loadReplies() {
    try {
      const data = await getPostReplies(id, { limit: 50 }, token);
      setReplies(data.posts);
    } finally {
      setReplyLoading(false);
    }
  }

  // Load on first render
  if (postLoading && !post) { loadPost(); }
  if (replyLoading && replies.length === 0 && !postLoading) { loadReplies(); }

  async function handleReply() {
    if (!compose.trim() || !token || !post) return;
    setPosting(true);
    try {
      await createPost(
        {
          post_type:  "UPDATE",
          title:      `Re: ${post.title}`.slice(0, 80),
          content:    compose,
          visibility: "PUBLIC",
          metadata:   { parent_post_id: id },
        },
        token,
      );
      setCompose("");
      loadReplies();
    } finally {
      setPosting(false);
    }
  }

  return (
    <AppShell>
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => router.back()}
          className="p-2 rounded-full hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={18} />
        </button>
        <h1 className="text-lg font-bold">Post</h1>
      </div>

      {/* Root post */}
      {postLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-primary" />
        </div>
      ) : post ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 mb-6 space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300">
              {post.post_type}
            </span>
            <span className="text-xs text-slate-500">{post.author_did}</span>
          </div>
          <h2 className="font-bold text-base">{post.title}</h2>
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">{post.content}</p>
        </div>
      ) : (
        <div className="py-12 text-center text-slate-500">Post not found.</div>
      )}

      {/* Reply compose */}
      {token && post && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 mb-6">
          <textarea
            className="w-full bg-transparent text-sm resize-none outline-none text-slate-200 placeholder:text-slate-500 mb-3"
            rows={3}
            placeholder={`Reply…`}
            value={compose}
            onChange={(e) => setCompose(e.target.value)}
          />
          <div className="flex justify-end">
            <button
              onClick={handleReply}
              disabled={!compose.trim() || posting}
              className="flex items-center gap-2 px-4 py-1.5 rounded-lg bg-primary text-white text-sm font-semibold disabled:opacity-40"
            >
              {posting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              Reply
            </button>
          </div>
        </div>
      )}

      {/* Replies */}
      <div className="space-y-3">
        {replyLoading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={20} className="animate-spin text-primary" />
          </div>
        )}
        {!replyLoading && replies.length === 0 && (
          <p className="text-center text-slate-500 text-sm py-8">
            No replies yet. Start the conversation!
          </p>
        )}
        {replies.map((reply) => (
          <div
            key={reply.post_id}
            className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 space-y-2"
          >
            <span className="text-xs text-slate-500">
              {reply.author_name ?? reply.author_did}
            </span>
            <p className="text-sm text-slate-300">{reply.content}</p>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
