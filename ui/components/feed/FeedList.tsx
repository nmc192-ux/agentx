import { PostCard } from "./PostCard";
import type { SocialPost } from "@/types";

export function FeedList({ posts }: { posts: SocialPost[] }) {
  if (!posts.length) {
    return (
      <div className="text-center py-12 text-slate-400">
        <p className="text-sm">No posts yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {posts.map((p, i) => (
        <PostCard key={p.post_id} post={p} index={i} />
      ))}
    </div>
  );
}
