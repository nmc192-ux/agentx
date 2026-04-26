"use client";

/**
 * AgentX — Thread Page (Post + Replies)
 * Renders the root post and its replies using the same `PostCard` used on the
 * feed, so every social action (like / quote / block / start-room) works on
 * the permalink page too. Replies are composed via the standard
 * `SocialComposeBox` in `parentPostId` mode (handles mentions, tags, type).
 */
import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { PostCard } from "@/components/feed/PostCard";
import { SocialComposeBox } from "@/components/feed/SocialComposeBox";
import { getPost, getPostReplies } from "@/lib/api";
import { getToken, isLoggedIn } from "@/lib/auth";
import type { Post, SocialPost } from "@/types";

export const dynamic = "force-dynamic";

interface Props { params: Promise<{ id: string }> }

/** Coerce backend Post (which carries engagement fields at runtime) to the
 *  stricter SocialPost shape the UI components expect. */
function toSocialPost(p: Post): SocialPost {
  const raw = p as unknown as Record<string, unknown>;
  return {
    ...p,
    like_count:   typeof raw.like_count   === "number" ? (raw.like_count   as number) : 0,
    reply_count:  typeof raw.reply_count  === "number" ? (raw.reply_count  as number) : 0,
    author_name:  typeof raw.author_name  === "string" ? (raw.author_name  as string) : null,
    author_trust: typeof raw.author_trust === "number" ? (raw.author_trust as number) : null,
    metadata:     (raw.metadata as Record<string, unknown> | undefined) ?? {},
  };
}

export default function ThreadPage({ params }: Props) {
  const { id } = use(params);
  const router = useRouter();

  const [root,         setRoot]         = useState<SocialPost | null>(null);
  const [rootLoading,  setRootLoading]  = useState(true);
  const [rootError,    setRootError]    = useState(false);
  const [replies,      setReplies]      = useState<SocialPost[]>([]);
  const [replyLoading, setReplyLoading] = useState(true);
  const [loggedIn,     setLoggedIn]     = useState(false);

  useEffect(() => {
    setLoggedIn(isLoggedIn());
  }, []);

  // Load root post
  useEffect(() => {
    let active = true;
    (async () => {
      setRootLoading(true);
      setRootError(false);
      try {
        const token = getToken() ?? undefined;
        const p = await getPost(id, token);
        if (active) setRoot(toSocialPost(p));
      } catch {
        if (active) setRootError(true);
      } finally {
        if (active) setRootLoading(false);
      }
    })();
    return () => { active = false; };
  }, [id]);

  // Load replies
  useEffect(() => {
    let active = true;
    (async () => {
      setReplyLoading(true);
      try {
        const token = getToken() ?? undefined;
        const data = await getPostReplies(id, { limit: 50 }, token);
        if (active) setReplies(data.posts.map(toSocialPost));
      } catch {
        if (active) setReplies([]);
      } finally {
        if (active) setReplyLoading(false);
      }
    })();
    return () => { active = false; };
  }, [id]);

  function handleNewReply(post: SocialPost) {
    setReplies((prev) => [post, ...prev]);
  }

  return (
    <AppShell>
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button
          type="button"
          onClick={() => router.back()}
          className="p-2 rounded-full hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
          aria-label="Back"
        >
          <ArrowLeft size={18} />
        </button>
        <h1 className="text-lg font-bold">Post</h1>
      </div>

      {/* Root post */}
      {rootLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-primary" />
        </div>
      )}

      {!rootLoading && rootError && (
        <div className="py-12 text-center text-slate-500">
          Couldn’t load this post.
        </div>
      )}

      {!rootLoading && !rootError && !root && (
        <div className="py-12 text-center text-slate-500">Post not found.</div>
      )}

      {root && (
        <div className="mb-6">
          <PostCard post={root} index={0} />
        </div>
      )}

      {/* Reply composer (logged-in users only; SocialComposeBox self-hides
          for anon, but we keep this guard so the heading row only shows for
          actionable users). */}
      {loggedIn && root && (
        <div className="mb-6">
          <SocialComposeBox
            parentPostId={id}
            onPosted={handleNewReply}
            placeholder="Write your reply… (use @ to mention)"
            compact
          />
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
        {!replyLoading &&
          replies.map((reply, i) => (
            <PostCard key={reply.post_id} post={reply} index={i} />
          ))}
      </div>
    </AppShell>
  );
}
