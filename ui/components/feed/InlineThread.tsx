"use client";

/**
 * AgentX — Inline Thread
 * Rendered under a PostCard when Reply is clicked. Fetches replies via
 * getPostReplies and lets the user post a reply with SocialComposeBox (compact).
 */
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getPostReplies } from "@/lib/api";
import { getToken } from "@/lib/auth";
import type { SocialPost } from "@/types";
import { PostCard } from "./PostCard";
import { SocialComposeBox } from "./SocialComposeBox";

interface Props {
  postId: string;
  onReplyPosted?: () => void;
}

export function InlineThread({ postId, onReplyPosted }: Props) {
  const [replies, setReplies] = useState<SocialPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const token = getToken() ?? undefined;
        const resp = await getPostReplies(postId, { limit: 20 }, token);
        if (!active) return;
        setReplies((resp.posts as SocialPost[]) ?? []);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load replies");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [postId]);

  function handleNewReply(post: SocialPost) {
    setReplies((prev) => [post, ...prev]);
    onReplyPosted?.();
  }

  return (
    <div className="mt-3 pl-3 border-l-2 border-slate-800 space-y-3">
      <SocialComposeBox
        parentPostId={postId}
        onPosted={handleNewReply}
        compact
      />

      {loading && (
        <div className="flex items-center gap-2 text-xs text-slate-500 py-2">
          <Loader2 className="w-3 h-3 animate-spin" />
          Loading replies…
        </div>
      )}

      {error && (
        <p className="text-xs text-red-400 py-2">{error}</p>
      )}

      {!loading && !error && replies.length === 0 && (
        <p className="text-xs text-slate-600 py-2">No replies yet.</p>
      )}

      <div className="space-y-2">
        {replies.map((r, i) => (
          <PostCard key={r.post_id} post={r} index={i} />
        ))}
      </div>
    </div>
  );
}
