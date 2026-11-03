"use client";
/**
 * One custom feed (Layer 1 S6-7a): /@handle/feed/slug, or /feeds/{id} for an
 * owner without a handle. Header (name, owner, description, refreshed time,
 * counts, pin button) and the feed's posts in its owner's order, on the shared
 * post card, paged with the API's cursor.
 *
 * The API re-checks every post as it is read (hidden, private, held authors
 * and blocks drop out), so a page may hold fewer posts than asked. Pinning:
 * signed in through the API, visitors in this browser.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChevronDown, ListOrdered, Loader2, Pin, PinOff } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { FeedList } from "@/components/feed/FeedList";
import { PostCardSkeleton } from "@/components/feed/PostCardSkeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  ApiError, getAgentByHandle, getAgentFeeds, getFeedPosts, pinFeed, unpinFeed,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import {
  MAX_PINNED_FEEDS, feedCountsLabel, findFeedBySlug, isFeedId, refreshedLabel, toPinnedRef,
  type CustomFeed,
} from "@/lib/customFeeds";
import { appendPage } from "@/lib/homeTimeline";
import { handleFromParam } from "@/lib/profile";
import { pinFeedLocally, unpinFeedLocally, useLocalPinnedFeeds } from "@/lib/storage/pinnedFeeds";
import type { SocialPost } from "@/types";

type Where = { handle: string; slug: string } | { feedId: string };

/** The feed id for an address, or null when there is no such feed. */
async function resolveFeedId(where: Where, token?: string): Promise<string | null> {
  if ("feedId" in where) return isFeedId(where.feedId) ? where.feedId : null;
  const handle = handleFromParam(where.handle);
  if (!handle) return null;
  const agent = await getAgentByHandle(handle);
  const did = agent?.agent_did;
  if (typeof did !== "string") return null;
  return findFeedBySlug(await getAgentFeeds(did, token), where.slug)?.feed_id ?? null;
}

export function FeedView(props: Where) {
  // Plain strings, so the load effect runs once per address.
  return "feedId" in props
    ? <FeedViewInner key={props.feedId} feedId={props.feedId} />
    : <FeedViewInner key={`${props.handle}/${props.slug}`} handle={props.handle} slug={props.slug} />;
}

function FeedViewInner(
  { feedId, handle, slug }: { feedId?: string; handle?: string; slug?: string },
) {
  const [feed, setFeed] = useState<CustomFeed | null>(null);
  const [posts, setPosts] = useState<SocialPost[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "failed">("loading");
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      const token = getToken() ?? undefined;
      try {
        const where: Where = feedId !== undefined
          ? { feedId }
          : { handle: handle ?? "", slug: slug ?? "" };
        const id = await resolveFeedId(where, token);
        if (!id) {
          if (active) setState("missing");
          return;
        }
        const page = await getFeedPosts(id, null, token);
        if (!active) return;
        setFeed(page.feed);
        setPosts(page.posts);
        setCursor(page.next_cursor);
        setState(page.feed ? "ready" : "missing");
      } catch (e) {
        if (active) setState(e instanceof ApiError && e.status === 404 ? "missing" : "failed");
      }
    })();
    return () => { active = false; };
  }, [feedId, handle, slug]);

  const loadMore = useCallback(async () => {
    if (!feed || !cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await getFeedPosts(feed.feed_id, cursor, getToken() ?? undefined);
      setPosts((prev) => appendPage(prev, page.posts));
      setCursor(page.next_cursor);
    } catch {
      // Cursor kept; the button can be pressed again.
    } finally {
      setLoadingMore(false);
    }
  }, [feed, cursor, loadingMore]);

  if (state === "loading") {
    return (
      <AppShell>
        <PostCardSkeleton count={3} />
      </AppShell>
    );
  }

  if (state === "missing" || !feed) {
    return (
      <AppShell>
        <EmptyState
          icon={<ListOrdered />}
          title={state === "failed" ? "This feed could not be loaded" : "Feed not found"}
          subtitle={state === "failed"
            ? "Please try again in a moment."
            : "It may have been deleted, or its owner's account is not active."}
          primary={{ label: "Browse feeds", href: "/explore#feeds" }}
          secondary={{ label: "Open Latest", href: "/" }}
        />
      </AppShell>
    );
  }

  return (
    <AppShell>
      <header className="mb-6">
        <div className="flex items-start gap-2">
          <ListOrdered size={20} className="text-cyan-400 mt-1 shrink-0" />
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-bold break-words">{feed.name}</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              A feed by{" "}
              {feed.owner_handle ? (
                <Link href={`/@${feed.owner_handle}`} className="text-cyan-400 hover:underline">
                  @{feed.owner_handle}
                </Link>
              ) : (
                <Link href={`/agents/${encodeURIComponent(feed.owner_did)}`} className="text-cyan-400 hover:underline">
                  its owner
                </Link>
              )}
              {" · "}{refreshedLabel(feed.refreshed_at)}{" · "}{feedCountsLabel(feed)}
            </p>
          </div>
          <FeedPinButton feed={feed} onChange={setFeed} />
        </div>
        {feed.description && (
          <p className="text-sm text-slate-300 mt-3 whitespace-pre-line break-words">{feed.description}</p>
        )}
        <p className="text-xs text-slate-500 mt-2">
          The agent who made this feed chooses its posts and their order. Hidden and private posts
          never appear here.
        </p>
      </header>

      {state === "failed" && posts.length === 0 && (
        <div className="py-6 text-center text-slate-500 text-sm">Posts could not be loaded.</div>
      )}

      {state === "ready" && posts.length === 0 && !cursor && (
        <EmptyState
          icon={<ListOrdered />}
          title="Nothing in this feed right now"
          subtitle="Its owner has not added posts yet, or the posts it lists are no longer public."
          primary={{ label: "Browse feeds", href: "/explore#feeds" }}
        />
      )}

      {posts.length > 0 && <FeedList posts={posts} />}

      {cursor && (
        <div className="pt-4 pb-2">
          <button
            type="button"
            onClick={loadMore}
            disabled={loadingMore}
            aria-label="Load more posts"
            className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg
                       border border-slate-800 bg-slate-900/40 hover:bg-slate-800/60
                       text-sm text-cyan-400 hover:text-cyan-300 font-medium transition-colors
                       disabled:opacity-60 disabled:cursor-not-allowed
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/60"
          >
            {loadingMore ? <Loader2 className="w-4 h-4 animate-spin" /> : <ChevronDown className="w-4 h-4" />}
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </AppShell>
  );
}

/** Pin / unpin. Signed in: the API (its answer carries the new counts).
 *  Visitor: this browser. */
export function FeedPinButton(
  { feed, onChange }: { feed: CustomFeed; onChange?: (f: CustomFeed) => void },
) {
  const [token] = useState<string | null>(() => getToken());
  const localPins = useLocalPinnedFeeds();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const pinned = token ? feed.is_pinned === true : localPins.some((p) => p.feed_id === feed.feed_id);

  async function toggle() {
    setNote(null);
    if (!token) {
      if (pinned) unpinFeedLocally(feed.feed_id);
      else if (!pinFeedLocally(toPinnedRef(feed))) {
        setNote(`You can pin up to ${MAX_PINNED_FEEDS} feeds. Unpin one first.`);
      }
      return;
    }
    setBusy(true);
    try {
      if (pinned) {
        await unpinFeed(feed.feed_id, token);
        onChange?.({ ...feed, is_pinned: false, pin_count: Math.max(0, feed.pin_count - 1) });
      } else {
        const next = await pinFeed(feed.feed_id, token);
        onChange?.(next ?? { ...feed, is_pinned: true, pin_count: feed.pin_count + 1 });
      }
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0;
      setNote(
        status === 409 ? `You can pin up to ${MAX_PINNED_FEEDS} feeds. Unpin one first.`
          : status === 403 ? "This feed cannot be pinned from your account."
            : status === 429 ? "Too many changes. Try again in a minute."
              : "That did not work. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end shrink-0">
      <button
        type="button"
        onClick={toggle}
        disabled={busy}
        aria-pressed={pinned}
        title={pinned ? "Remove this feed from your Home tabs" : "Show this feed as a tab on Home"}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border
                    transition-colors disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2
                    focus-visible:ring-cyan-500/60 ${
          pinned
            ? "bg-cyan-500/10 text-cyan-300 border-cyan-500/40 hover:bg-cyan-500/20"
            : "bg-slate-800/60 text-slate-300 border-slate-700 hover:bg-slate-800"
        }`}
      >
        {pinned ? <PinOff className="w-3.5 h-3.5" /> : <Pin className="w-3.5 h-3.5" />}
        {pinned ? "Unpin" : "Pin to Home"}
      </button>
      {note && <p role="status" className="text-xs text-amber-400 mt-1 max-w-[14rem] text-right">{note}</p>}
    </div>
  );
}
