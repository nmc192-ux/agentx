"use client";
import { use } from "react";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { getPost, getPostReplies } from "@/lib/api";
import { PostCard } from "@/components/PostCard";
import { ComposeBox } from "@/components/ComposeBox";
import { TwitterShell } from "@/components/TwitterShell";
import type { SocialPost } from "@/types";

interface Props { params: Promise<{ id: string }> }

export default function ThreadPage({ params }: Props) {
  const { id } = use(params);
  const router = useRouter();
  const { data: session } = useSession();
  const token = (session as any)?.accessToken as string | undefined;

  const { data: post, isLoading: postLoading } = useQuery({
    queryKey: ["post", id],
    queryFn: () => getPost(id, token),
    staleTime: 30_000,
  });

  const { data: repliesData, isLoading: repliesLoading, refetch } = useQuery({
    queryKey: ["replies", id],
    queryFn: () => getPostReplies(id, { limit: 50 }, token),
    staleTime: 15_000,
  });

  const rootPost: SocialPost | undefined = post
    ? {
        ...(post as any),
        like_count:   (post as any).like_count   ?? 0,
        reply_count:  (post as any).reply_count  ?? 0,
        author_name:  (post as any).author_name  ?? null,
        author_trust: (post as any).author_trust ?? null,
        metadata:     (post as any).metadata     ?? {},
      }
    : undefined;

  return (
    <TwitterShell showRightSidebar={false}>
      {/* Header */}
      <div className="sticky top-0 z-10 backdrop-blur-md bg-background-primary/80 border-b border-border-primary px-4 py-3 flex items-center gap-3">
        <button
          onClick={() => router.back()}
          className="text-text-secondary hover:text-text-primary transition-colors p-1 rounded-full hover:bg-surface-primary"
        >
          <ArrowLeft size={20} />
        </button>
        <h1 className="text-lg font-bold text-text-primary">Post</h1>
      </div>

      {/* Root post */}
      {postLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-accent-primary" />
        </div>
      ) : rootPost ? (
        <PostCard post={rootPost} compact />
      ) : (
        <div className="px-4 py-12 text-center text-text-tertiary">Post not found.</div>
      )}

      {/* Reply compose */}
      {session && rootPost && (
        <ComposeBox
          parentPostId={id}
          onPosted={() => refetch()}
          placeholder={`Reply to ${rootPost.author_name ?? "this post"}…`}
        />
      )}

      {/* Replies */}
      <div className="border-t border-border-primary">
        {repliesLoading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={20} className="animate-spin text-accent-primary" />
          </div>
        )}

        {!repliesLoading && (repliesData?.posts ?? []).length === 0 && (
          <div className="px-4 py-8 text-center text-text-tertiary text-sm">
            No replies yet. Start the conversation!
          </div>
        )}

        {(repliesData?.posts ?? []).map((reply: SocialPost) => (
          <PostCard key={reply.post_id} post={reply} />
        ))}
      </div>
    </TwitterShell>
  );
}
