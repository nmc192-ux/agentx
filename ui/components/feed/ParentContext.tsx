"use client";

/**
 * AgentX — Parent post context for /post/[id] permalinks
 *
 * When you land on a permalink that's itself a reply, today the page
 * shows just the reply with no anchoring context. Twitter and Bluesky
 * both surface the parent above the reply so you can read the
 * conversation in order — without it, replies on the open web feel
 * like overheard half-sentences.
 *
 * This component fetches the parent and renders it as a compact card:
 *
 *   ┌─ "Replying to this post" header ─────────────────┐
 *   │  avatar  display_name · 2 h ago                  │
 *   │          [optional title]                        │
 *   │          content excerpt (line-clamp-2)          │
 *   └──────────────────────────────────────────────────┘
 *
 * The whole card is a `<Link>` to the parent's own permalink, so users
 * can step up the chain one post at a time. Loading shows a spinner;
 * the error state still renders a navigable "View parent post →" link
 * so users aren't stranded if the fetch fails.
 *
 * Self-fetching (rather than receiving the post from the parent page)
 * keeps the /post/[id] page's data flow straightforward — the page
 * doesn't need to know whether to fetch a parent until *after* it has
 * the root, and we'd rather not wait sequentially. Letting this
 * component drive its own request means it kicks off as soon as it
 * mounts, in parallel with whatever else the page is doing.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, MessageSquare } from "lucide-react";
import { getPost } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { shortDid, timeAgo } from "@/lib/utils";
import type { Post } from "@/types";

interface Props {
  parentPostId: string;
}

export function ParentContext({ parentPostId }: Props) {
  const [parent, setParent] = useState<Post | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    (async () => {
      try {
        const token = getToken() ?? undefined;
        const p = await getPost(parentPostId, token);
        if (active) setParent(p);
      } catch {
        if (active) setError(true);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [parentPostId]);

  // Loading skeleton — keeps the layout from jumping when the fetch
  // resolves. Same outer dimensions as the populated card.
  if (loading) {
    return (
      <div
        className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 mb-3 flex items-center justify-center min-h-[88px]"
        aria-busy="true"
        aria-live="polite"
      >
        <Loader2 className="w-4 h-4 animate-spin text-slate-500" />
      </div>
    );
  }

  // Fallback when the parent fetch fails (deleted post, permission error,
  // network blip). Still navigable so users can try the permalink directly
  // — Bluesky / Twitter do the same: the link remains even when the
  // preview can't render.
  if (error || !parent) {
    return (
      <Link
        href={`/post/${parentPostId}`}
        className="block rounded-xl border border-slate-800 bg-slate-900/40 p-3 mb-3 text-xs text-slate-500 hover:bg-slate-800/40 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/60"
      >
        <MessageSquare className="w-3 h-3 inline mr-1.5 -mt-0.5" />
        View parent post →
      </Link>
    );
  }

  // Backend may flatten author fields onto the Post envelope (engagement
  // hydration) or may not — accept either shape so the component works
  // against the bare `Post` type and the richer SocialPost-shaped runtime
  // value the API often returns.
  const flat = parent as Post & {
    author_name?: string | null;
  };
  const display = flat.author_name ?? shortDid(parent.author_did);
  const initials =
    (parent.author_did.split(":").pop() ?? "A").slice(0, 2).toUpperCase();

  return (
    <Link
      href={`/post/${parent.post_id}`}
      className="block mb-3 rounded-xl border border-slate-800 bg-slate-900/40 p-4 hover:bg-slate-800/40 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/60"
      aria-label={`View parent post by ${display}`}
    >
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-500 mb-2">
        <MessageSquare className="w-3 h-3" />
        Replying to this post
      </div>
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-blue-400 flex items-center justify-center text-[10px] font-bold text-white shrink-0">
          {initials}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 min-w-0">
            <span className="text-sm font-medium text-slate-100 truncate min-w-0">
              {display}
            </span>
            <span className="text-[11px] text-slate-500 font-mono truncate min-w-0">
              @{shortDid(parent.author_did)}
            </span>
            <time
              dateTime={parent.created_at}
              title={new Date(parent.created_at).toLocaleString()}
              className="text-[11px] text-slate-500 shrink-0 tabular-nums ml-auto"
            >
              {timeAgo(parent.created_at)}
            </time>
          </div>
          {parent.title && (
            <p className="text-sm font-medium text-slate-200 truncate mt-0.5">
              {parent.title}
            </p>
          )}
          {parent.content && (
            <p className="text-sm text-slate-400 line-clamp-2 mt-1 whitespace-pre-wrap">
              {parent.content}
            </p>
          )}
        </div>
      </div>
    </Link>
  );
}
