"use client";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { getPostReplies } from "@/lib/api";
import { PostCard } from "./PostCard";
import type { SocialPost } from "@/types";

interface Props {
  postId:     string;
  replyCount: number;
}

export function CommentThread({ postId, replyCount }: Props) {
  const { data: session } = useSession();
  const token = (session as any)?.accessToken as string | undefined;

  const { data, isLoading } = useQuery({
    queryKey: ["thread-replies", postId],
    queryFn:  () => getPostReplies(postId, { limit: 3 }, token),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-4 py-2 text-xs text-text-tertiary">
        <Loader2 size={12} className="animate-spin" />
        Loading replies…
      </div>
    );
  }

  const replies: SocialPost[] = data?.posts ?? [];
  if (!replies.length) {
    return (
      <p className="px-4 py-2 text-xs text-text-tertiary italic">No replies yet.</p>
    );
  }

  const shown = replies.slice(0, 3);

  return (
    <div className="border-t border-border-primary/30 bg-surface-primary/50">
      {shown.map(reply => (
        <div key={reply.post_id} className="pl-10 border-l-2 border-border-primary/20 ml-6">
          <PostCard post={reply} compact />
        </div>
      ))}
      {replyCount > 3 && (
        <Link
          href={`/post/${postId}`}
          onClick={e => e.stopPropagation()}
          className="block px-4 py-2 text-xs text-accent-primary hover:underline"
        >
          View all {replyCount} replies →
        </Link>
      )}
    </div>
  );
}
