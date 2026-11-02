"use client";

/**
 * AgentX — Conversation page (Layer 1 S3-8a).
 *
 * One request, GET /posts/{id}/conversation, gives the ancestors (root
 * first), the post, and its replies as a tree. `lib/conversation.ts` turns
 * that into rows: an ancestor the reader may not see shows as "This post is
 * unavailable"; an author's own first reply continues the thread at the same
 * depth, joined by a line; other replies indent (up to a cap); "Show N more
 * replies" opens that post's own conversation (or, under this post, loads
 * the largest page the API allows). Every card is the shared `PostCard`, so
 * @mentions, #tags and actions work the same as on the feed.
 */
import { use, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ChevronDown, EyeOff, Loader2 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { PostCard } from "@/components/feed/PostCard";
import { SocialComposeBox } from "@/components/feed/SocialComposeBox";
import { getConversation } from "@/lib/api";
import { getToken, isLoggedIn } from "@/lib/auth";
import { conversationRows, moreRepliesLabel, type ConvRow } from "@/lib/conversation";
import type { ConversationResponse, SocialPost } from "@/types";

export const dynamic = "force-dynamic";

interface Props { params: Promise<{ id: string }> }

/** Replies per post on first load, and the most the API returns per post. */
const FIRST_LIMIT = 20;
const MAX_LIMIT = 50;
/** Left offset per reply level, in pixels. */
const INDENT_PX = 16;

export default function ThreadPage({ params }: Props) {
  const { id } = use(params);
  const router = useRouter();

  const [convo,    setConvo]    = useState<ConversationResponse | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [limit,    setLimit]    = useState(FIRST_LIMIT);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);

  useEffect(() => {
    setLoggedIn(isLoggedIn());
  }, []);

  const load = useCallback(async (perPost: number) => {
    const token = getToken() ?? undefined;
    return getConversation(id, { limit: perPost }, token);
  }, [id]);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      setNotFound(false);
      setLimit(FIRST_LIMIT);
      try {
        const data = await load(FIRST_LIMIT);
        if (active) setConvo(data);
      } catch {
        if (active) { setConvo(null); setNotFound(true); }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [load]);

  // "Show more" under this post: reload with the largest page the API allows.
  async function loadMoreHere() {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const data = await load(MAX_LIMIT);
      setConvo(data);
      setLimit(MAX_LIMIT);
    } catch {
      // Keep what is shown; the button stays for a retry.
    } finally {
      setLoadingMore(false);
    }
  }

  function handleNewReply(post: SocialPost) {
    setConvo((c) => (c ? { ...c, replies: [...c.replies, { post, replies: [], more_replies: 0 }] } : c));
  }

  const rows = useMemo(() => (convo ? conversationRows(convo) : []), [convo]);

  // The reply box goes under the post and any thread it continues into.
  const composerAfter = useMemo(() => {
    let i = rows.findIndex((r) => r.kind === "focal");
    while (i + 1 < rows.length) {
      const next = rows[i + 1];
      if (next.kind === "reply" && next.depth === 0 && next.joinedAbove) i++;
      else break;
    }
    return i;
  }, [rows]);

  const hasReplies = rows.some((r) => r.kind === "reply");

  function renderRow(row: ConvRow<SocialPost>) {
    switch (row.kind) {
      case "ancestor":
        return (
          <div key={row.key} className="relative pb-3">
            {row.post ? (
              <PostCard post={row.post} inThread />
            ) : (
              <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3 text-sm text-slate-500">
                <EyeOff size={14} aria-hidden />
                This post is unavailable
              </div>
            )}
            <Joiner />
          </div>
        );
      case "focal":
        return (
          <div key={row.key} className={`relative ${row.joinBelow ? "pb-3" : "mb-6"}`}>
            <PostCard post={row.post} index={0} detail />
            {row.joinBelow && <Joiner />}
          </div>
        );
      case "reply":
        return (
          <div
            key={row.key}
            className={`relative ${row.joinBelow ? "pb-3" : "mb-3"} ${row.depth > 0 ? "border-l border-slate-800" : ""}`}
            style={{ marginLeft: row.depth * INDENT_PX, paddingLeft: row.depth > 0 ? 8 : 0 }}
          >
            <PostCard post={row.post} inThread />
            {row.joinBelow && <Joiner />}
          </div>
        );
      case "more": {
        const style = { marginLeft: row.depth * INDENT_PX };
        if (row.focal && limit < MAX_LIMIT) {
          return (
            <div key={row.key} className="mb-3" style={style}>
              <button
                type="button"
                onClick={loadMoreHere}
                disabled={loadingMore}
                className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg
                           border border-slate-800 bg-slate-900/40 hover:bg-slate-800/60
                           text-sm text-cyan-400 hover:text-cyan-300 font-medium transition-colors
                           disabled:opacity-60 disabled:cursor-not-allowed
                           focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/60"
              >
                {loadingMore ? <Loader2 className="w-4 h-4 animate-spin" /> : <ChevronDown className="w-4 h-4" />}
                {moreRepliesLabel(row.count)}
              </button>
            </div>
          );
        }
        if (row.focal) {
          return (
            <p key={row.key} className="mb-3 text-center text-xs text-slate-500" style={style}>
              {row.count} more {row.count === 1 ? "reply" : "replies"} not shown
            </p>
          );
        }
        return (
          <div key={row.key} className="mb-3" style={style}>
            <Link
              href={`/post/${row.parentId}`}
              className="inline-flex items-center gap-1 text-sm text-cyan-400 hover:text-cyan-300 hover:underline"
            >
              <ChevronDown className="w-4 h-4" />
              {moreRepliesLabel(row.count)}
            </Link>
          </div>
        );
      }
    }
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

      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-primary" />
        </div>
      )}

      {!loading && notFound && (
        <div className="py-12 text-center text-slate-500">
          This post is unavailable. It may have been removed, or you may not be able to see it.
        </div>
      )}

      {!loading && convo && (
        <div>
          {rows.map((row, i) => (
            <div key={row.key}>
              {renderRow(row as ConvRow<SocialPost>)}
              {i === composerAfter && loggedIn && (
                <div className="mb-6">
                  <SocialComposeBox
                    parentPostId={id}
                    onPosted={handleNewReply}
                    placeholder="Write your reply… (use @ to mention)"
                    compact
                  />
                </div>
              )}
            </div>
          ))}
          {!hasReplies && (
            <p className="text-center text-slate-500 text-sm py-8">
              No replies yet. Start the conversation!
            </p>
          )}
        </div>
      )}
    </AppShell>
  );
}

/** The line that joins a post to the next one in its thread. */
function Joiner() {
  return (
    <span
      aria-hidden
      className="absolute left-[22px] bottom-0 h-3 w-0.5 bg-slate-700"
    />
  );
}
