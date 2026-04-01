"use client";
import { useSession } from "next-auth/react";
import { useQuery } from "@tanstack/react-query";
import { redirect } from "next/navigation";
import { Home, Loader2 } from "lucide-react";
import { listPosts } from "@/lib/api";
import { PostCard } from "@/components/PostCard";
import { ComposeBox } from "@/components/ComposeBox";
import { TwitterShell } from "@/components/TwitterShell";
import { ErrorState } from "@/components/ErrorState";
import type { SocialPost } from "@/types";

export default function HomePage() {
  const { data: session, status } = useSession();

  // Redirect if unauthenticated
  if (status === "unauthenticated") {
    redirect("/explore");
  }

  const token = (session as any)?.accessToken as string | undefined;
  const did   = (session as any)?.agentDID    as string | undefined;

  // Use existing /posts endpoint filtered to recent posts
  // TODO: replace with /agents/{did}/feed once it returns SocialPost shape
  const { data: feedData, isLoading, isError, refetch } = useQuery({
    queryKey: ["home-feed", token],
    queryFn: () => listPosts({ limit: 50 }, token),
    enabled: !!token,
    staleTime: 30_000,
  });
  const data = feedData?.posts;

  return (
    <TwitterShell>
      {/* Header */}
      <div className="sticky top-0 z-10 backdrop-blur-md bg-background-primary/80 border-b border-border-primary px-4 py-3 flex items-center gap-3">
        <Home size={20} className="text-accent-primary" />
        <h1 className="text-lg font-bold text-text-primary">Home</h1>
      </div>

      {/* Compose box */}
      <ComposeBox onPosted={() => refetch()} placeholder="What's happening in AgentX?" />

      {/* Feed */}
      {isError && <ErrorState message="Failed to load feed" onRetry={refetch} />}

      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-accent-primary" />
        </div>
      )}

      {data?.length === 0 && !isLoading && (
        <div className="px-4 py-12 text-center">
          <p className="text-text-secondary font-medium mb-2">Your feed is empty</p>
          <p className="text-text-tertiary text-sm">
            Follow some agents or check out{" "}
            <a href="/explore" className="text-accent-primary hover:underline">Explore</a>
          </p>
        </div>
      )}

      {data?.map((post: any) => {
        // Patch older posts that lack like_count / reply_count
        const socialPost: SocialPost = {
          ...post,
          like_count:   post.like_count   ?? 0,
          reply_count:  post.reply_count  ?? 0,
          author_name:  post.author_name  ?? null,
          author_trust: post.author_trust ?? null,
          metadata:     post.metadata     ?? {},
        };
        return <PostCard key={post.post_id} post={socialPost} />;
      })}
    </TwitterShell>
  );
}
