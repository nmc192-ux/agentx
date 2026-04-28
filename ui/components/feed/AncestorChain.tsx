"use client";

/**
 * AgentX — Ancestor chain for /post/[id] permalinks
 *
 * When you land on a permalink that's a deep reply, today the page
 * shows just the *immediate* parent above it (via ParentContext). For a
 * 3+ level deep reply that means stepping up the chain one click at a
 * time to understand the conversation. Twitter / Bluesky both render
 * the ancestor stack (typically 2-3 levels) above the focused post so
 * users can read the thread in order without permalink-hopping.
 *
 * This component walks the `parent_post_id` chain client-side via
 * repeated `getPost` calls, capping at MAX_ANCESTORS to keep the page
 * from ballooning on a 50-deep chain. If the chain extends beyond the
 * cap, we surface a "View earlier in thread →" link at the top so
 * users can jump to the topmost fetched ancestor and continue the
 * climb from there. Same affordance Twitter and Bluesky use when an
 * ancestor stack is partially hidden.
 *
 * The walk stops on:
 *   1. depth = MAX_ANCESTORS reached
 *   2. parent_post_id absent (we've reached the thread root)
 *   3. fetch fails (network / deleted / permission)
 * Cases 2 and 3 terminate the chain — whatever's been collected still
 * renders, so a partial chain is always preferable to an empty
 * placeholder.
 *
 * Sequential fetches (each ancestor's id only resolves after fetching
 * the one below it) are unavoidable without a backend chain endpoint.
 * Mitigated by **incremental render**: each ancestor pushes onto state
 * as it arrives, so the immediate parent appears at ~150ms, the
 * grandparent at ~300ms, etc. — the user never sees a long blank
 * placeholder.
 *
 * Replaces the simpler ParentContext (which fetched and rendered only
 * the immediate parent) on /post/[id]; ParentContext.tsx is kept as
 * dead code for now in case other surfaces want the single-level
 * behavior — a follow-up cleanup can delete it.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUp, Loader2, MessageSquare } from "lucide-react";
import { getPost } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { shortDid, timeAgo } from "@/lib/utils";
import type { Post } from "@/types";

interface Props {
  parentPostId: string;
}

// How many ancestors to walk before stopping. 3 mirrors Twitter /
// Bluesky's typical stack depth — enough to anchor a reply in context
// without making the permalink page feel like a wall of cards. The
// "View earlier in thread →" link covers deeper chains.
const MAX_ANCESTORS = 3;

/**
 * Read the parent_post_id off a Post in either of the two shapes the
 * backend may return: top-level `parent_post_id` field, or nested
 * under `metadata.parent_post_id`. Returns null when neither resolves
 * to a non-empty string.
 *
 * The bare `Post` type doesn't declare these fields (they live on
 * `SocialPost`), but the runtime payload always includes them — same
 * shape mismatch handled by `toSocialPost` in app/post/[id]/page.tsx.
 * We coerce through `Record<string, unknown>` to read both.
 */
function readParentId(p: Post): string | null {
  const raw = p as unknown as Record<string, unknown>;
  const flat = raw.parent_post_id;
  const metadata = raw.metadata as Record<string, unknown> | undefined;
  const meta = metadata?.parent_post_id;
  if (typeof flat === "string" && flat) return flat;
  if (typeof meta === "string" && meta) return meta;
  return null;
}

export function AncestorChain({ parentPostId }: Props) {
  // Chain order: oldest-first walk into `chain` would be hard because
  // we discover ancestors newest-to-oldest. So we store them in walk
  // order (immediate parent at index 0, grandparent at 1, etc.) and
  // reverse only for display.
  const [chain, setChain] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  // True when we hit MAX_ANCESTORS but the topmost-fetched ancestor
  // still had a parent_post_id of its own — i.e. there's at least one
  // more level above what we rendered. Drives the "View earlier in
  // thread →" link.
  const [hasMoreAbove, setHasMoreAbove] = useState(false);
  // True when even the immediate parent failed to fetch — fall back to
  // a plain navigable link so the user isn't stranded.
  const [fatalError, setFatalError] = useState(false);

  useEffect(() => {
    let active = true;

    (async () => {
      // Reset state inside the async IIFE rather than synchronously in
      // the effect body — synchronous setState in an effect triggers
      // cascading renders (lint: react-hooks/set-state-in-effect). The
      // resets happen on the same microtask either way; visually
      // identical from the user's perspective.
      setChain([]);
      setLoading(true);
      setHasMoreAbove(false);
      setFatalError(false);

      const token = getToken() ?? undefined;
      let nextId: string | null = parentPostId;
      const collected: Post[] = [];

      for (let depth = 0; depth < MAX_ANCESTORS; depth++) {
        if (!nextId) break;
        try {
          const p = await getPost(nextId, token);
          if (!active) return;
          collected.push(p);
          // Incremental render — flush state on each successful fetch
          // so users see the chain build up rather than waiting for
          // the entire walk to complete.
          setChain([...collected]);
          nextId = readParentId(p);
        } catch {
          // Mid-chain fetch failure: terminate. If we hadn't even
          // gotten the immediate parent, mark fatal so the empty
          // state shows the navigable fallback link.
          if (collected.length === 0) {
            if (active) setFatalError(true);
          }
          nextId = null;
          break;
        }
      }

      if (!active) return;
      // Loop exited cleanly with MAX hit and there's still a parent
      // above the topmost fetched ancestor — signal "more above".
      if (nextId && collected.length === MAX_ANCESTORS) {
        setHasMoreAbove(true);
      }
      setLoading(false);
    })();

    return () => {
      active = false;
    };
  }, [parentPostId]);

  // First-fetch loading skeleton — same vertical footprint as a single
  // ancestor card so the layout doesn't jump when the first ancestor
  // resolves and the chain starts to grow downward (we add cards
  // BELOW the one we render here).
  if (loading && chain.length === 0) {
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

  // Fatal error / empty: same fallback as the old ParentContext —
  // a navigable link so the user can still drill into the parent
  // permalink directly even when the preview can't render.
  if (fatalError || chain.length === 0) {
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

  // Render chain top-to-bottom oldest-first. `chain` is walk order
  // (parent at 0, grandparent at 1, ...). Display order is the
  // reverse: oldest at top so reading downward = chronological.
  const displayChain = [...chain].reverse();
  const topmost = chain[chain.length - 1];

  return (
    <div className="mb-3" aria-label="Conversation context">
      {hasMoreAbove && (
        <Link
          href={`/post/${topmost.post_id}`}
          className="flex items-center gap-1.5 mb-1.5 px-3 py-1.5 rounded-lg
                     text-[11px] text-slate-400 hover:text-cyan-400
                     hover:bg-cyan-500/5 transition-colors w-fit
                     focus-visible:outline-none focus-visible:ring-2
                     focus-visible:ring-cyan-500/60"
          aria-label="View earlier in thread"
        >
          <ArrowUp className="w-3 h-3" />
          View earlier in thread
        </Link>
      )}

      {/* Stacked ancestor cards. Spacing is tighter than the focused
          post below them so the cluster reads as "context above the
          focused post" rather than three coequal cards. The vertical
          space-y-1.5 also visually clusters the chain. */}
      <div className="space-y-1.5" role="list">
        {displayChain.map((p, i) => (
          <AncestorCard
            key={p.post_id}
            post={p}
            isImmediate={i === displayChain.length - 1}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * Single ancestor card — compact author row + line-clamp-2 content +
 * timestamp. The whole card is a Link to that post's permalink so
 * users can step up the chain one post at a time (same as
 * ParentContext today). The immediate parent gets a slightly stronger
 * visual treatment ("Replying to this post" header) since it's the
 * most directly relevant; older ancestors are slightly de-emphasized.
 */
function AncestorCard({
  post,
  isImmediate,
}: {
  post: Post;
  isImmediate: boolean;
}) {
  // Backend may flatten author fields onto the Post envelope or not —
  // accept either shape (same dual-shape handling as ParentContext).
  const flat = post as Post & { author_name?: string | null };
  const display = flat.author_name ?? shortDid(post.author_did);
  const initials =
    (post.author_did.split(":").pop() ?? "A").slice(0, 2).toUpperCase();

  // Older ancestors (non-immediate) get a more muted background so the
  // user's eye is drawn down toward the immediate parent + focused post
  // rather than spread evenly across the stack.
  const cardClass = isImmediate
    ? "block rounded-xl border border-slate-800 bg-slate-900/40 p-4 hover:bg-slate-800/40 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/60"
    : "block rounded-xl border border-slate-800/70 bg-slate-900/25 p-3 hover:bg-slate-800/30 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/60";

  const avatarSize = isImmediate ? "w-8 h-8 text-[10px]" : "w-7 h-7 text-[9px]";

  return (
    <Link
      href={`/post/${post.post_id}`}
      className={cardClass}
      role="listitem"
      aria-label={`View post by ${display}`}
    >
      {isImmediate && (
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-500 mb-2">
          <MessageSquare className="w-3 h-3" />
          Replying to this post
        </div>
      )}
      <div className="flex items-start gap-3">
        <div
          className={`${avatarSize} rounded-full bg-gradient-to-br from-primary to-blue-400 flex items-center justify-center font-bold text-white shrink-0`}
        >
          {initials}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 min-w-0">
            <span
              className={`${
                isImmediate ? "text-sm" : "text-[13px]"
              } font-medium text-slate-100 truncate min-w-0`}
            >
              {display}
            </span>
            <span className="text-[11px] text-slate-500 font-mono truncate min-w-0">
              @{shortDid(post.author_did)}
            </span>
            <time
              dateTime={post.created_at}
              title={new Date(post.created_at).toLocaleString()}
              className="text-[11px] text-slate-500 shrink-0 tabular-nums ml-auto"
            >
              {timeAgo(post.created_at)}
            </time>
          </div>
          {post.title && (
            <p
              className={`${
                isImmediate ? "text-sm" : "text-[13px]"
              } font-medium text-slate-200 truncate mt-0.5`}
            >
              {post.title}
            </p>
          )}
          {post.content && (
            <p
              className={`${
                isImmediate ? "text-sm" : "text-[13px]"
              } text-slate-400 ${
                isImmediate ? "line-clamp-2" : "line-clamp-1"
              } mt-1 whitespace-pre-wrap`}
            >
              {post.content}
            </p>
          )}
        </div>
      </div>
    </Link>
  );
}
