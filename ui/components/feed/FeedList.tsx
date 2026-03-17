import { PostCard } from "./PostCard";

export function FeedList({ posts }: { posts: Record<string, unknown>[] }) {
  if (!posts.length) {
    return (
      <div className="text-center py-12 text-slate-400">
        <span className="material-symbols-outlined text-4xl block mb-2">
          rss_feed
        </span>
        <p className="text-sm">No posts yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {posts.map((p) => (
        <PostCard key={(p.post_id as string) ?? Math.random().toString()} post={p} />
      ))}
    </div>
  );
}
