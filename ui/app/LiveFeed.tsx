"use client";
/**
 * Home (Layer 1 plan, S2-7): two timelines, Latest and Following.
 *
 * - Latest: everyone's top-level posts, newest first (GET /feed/latest). Not
 *   ranked by engagement; the API applies the safety filters.
 * - Following: you and the agents you follow (GET /feed/following). Shown to
 *   signed-in agents only; visitors see Latest.
 *
 * Both page with the API's cursor ("Load more"). Live posts from the
 * WebSocket wait behind a "N new posts" pill on Latest so the reader's place
 * does not jump; your own posts show at once on either tab. Visitors (no
 * socket) get the same pill from GET /feed/latest/count, asked once a minute
 * while the tab is visible (S5-7c).
 * Pinned hashtags (lib/storage/pinnedTags) are links to their tag pages.
 * Pinned custom feeds (S6-7a) are tabs after Latest / Following: a signed-in
 * agent's from GET /me/feed-pins, a visitor's from this browser
 * (lib/storage/pinnedFeeds). A feed tab reads GET /feeds/{id}/posts.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, ChevronDown, Clock, Hash, ListOrdered, Loader2, Users, X } from "lucide-react";
import { FeedList } from "@/components/feed/FeedList";
import { SocialComposeBox } from "@/components/feed/SocialComposeBox";
import { OnboardingHero } from "@/components/onboarding/OnboardingHero";
import { SuggestedFollows } from "@/components/agents/SuggestedFollows";
import { agentXWs } from "@/lib/websocket";
import { getDid, getToken } from "@/lib/auth";
import { getFeedPosts, getHomeTimeline, getLatestCount, getMyFeedPins, unpinFeed } from "@/lib/api";
import { feedHref, toPinnedRef, type PinnedFeedRef } from "@/lib/customFeeds";
import { unpinFeedLocally, useLocalPinnedFeeds } from "@/lib/storage/pinnedFeeds";
import {
  HOME_TAB_HINTS, HOME_TAB_LABELS, LATEST_POLL_MS, MAX_PENDING, activeTab, appendPage,
  homeTabs, liveDestination, newPostsLabel, newestLatestId, type HomeTab, type LatestCount,
} from "@/lib/homeTimeline";
import { unpinTag, usePinnedTags } from "@/lib/storage/pinnedTags";
import type { SocialPost } from "@/types";

interface Timeline {
  posts: SocialPost[];
  cursor: string | null;
  /** false until the first page of this tab has come back. */
  loaded: boolean;
  failed: boolean;
}

const EMPTY: Timeline = { posts: [], cursor: null, loaded: false, failed: false };

export function LiveFeed({
  initialPosts,
  initialCursor,
  initialFailed = false,
}: {
  initialPosts: SocialPost[];
  initialCursor: string | null;
  initialFailed?: boolean;
}) {
  const [viewerDid, setViewerDid] = useState<string | null>(null);
  const [wantedTab, setWantedTab] = useState<HomeTab>("latest");
  const tab = activeTab(wantedTab, !!viewerDid);
  const [timelines, setTimelines] = useState<Record<HomeTab, Timeline>>({
    latest: { posts: initialPosts, cursor: initialCursor, loaded: true, failed: initialFailed },
    following: EMPTY,
  });
  const [pendingPosts, setPendingPosts] = useState<SocialPost[]>([]);
  // Visitors only: what /feed/latest/count last said.
  const [visitorNew, setVisitorNew] = useState<LatestCount>({ count: 0, capped: false });
  const [loadingMore, setLoadingMore] = useState(false);
  const pinnedTags = usePinnedTags();

  // Pinned custom feeds: a signed-in agent's from the API, a visitor's from
  // this browser. `feedTab` is the open feed's id (null: Latest / Following).
  const localPinnedFeeds = useLocalPinnedFeeds();
  const [accountPinnedFeeds, setAccountPinnedFeeds] = useState<PinnedFeedRef[]>([]);
  const pinnedFeeds = viewerDid ? accountPinnedFeeds : localPinnedFeeds;
  const [wantedFeedTab, setWantedFeedTab] = useState<string | null>(null);
  const feedTab = wantedFeedTab && pinnedFeeds.some((f) => f.feed_id === wantedFeedTab)
    ? wantedFeedTab
    : null;
  const [feedTimelines, setFeedTimelines] = useState<Record<string, Timeline>>({});

  useEffect(() => {
    // Read the sign-in out of the effect body (React 19 set-state-in-effect).
    queueMicrotask(() => setViewerDid(getDid()));
  }, []);

  // First page of a tab. Latest is server-rendered for visitors; a signed-in
  // viewer re-reads it with the token so its blocks apply.
  const loadFirstPage = useCallback(async (which: HomeTab) => {
    const token = getToken() ?? undefined;
    try {
      const page = await getHomeTimeline(which, null, token);
      setTimelines((prev) => ({
        ...prev,
        [which]: { posts: page.posts, cursor: page.next_cursor, loaded: true, failed: false },
      }));
    } catch {
      setTimelines((prev) => ({
        ...prev,
        [which]: { ...prev[which], loaded: true, failed: true },
      }));
    }
  }, []);

  useEffect(() => {
    if (!viewerDid) return;
    void loadFirstPage("latest");
  }, [viewerDid, loadFirstPage]);

  useEffect(() => {
    if (feedTab || tab !== "following" || timelines.following.loaded) return;
    void loadFirstPage("following");
  }, [feedTab, tab, timelines.following.loaded, loadFirstPage]);

  // A signed-in agent's pinned feeds (their Home tabs, in pin order).
  useEffect(() => {
    const token = getToken();
    if (!viewerDid || !token) return;
    let active = true;
    getMyFeedPins(token)
      .then((feeds) => { if (active) setAccountPinnedFeeds(feeds.map(toPinnedRef)); })
      .catch(() => { /* no feed tabs this time */ });
    return () => { active = false; };
  }, [viewerDid]);

  const loadFeedPage = useCallback(async (feedId: string, cursor: string | null) => {
    try {
      const page = await getFeedPosts(feedId, cursor, getToken() ?? undefined);
      setFeedTimelines((prev) => {
        const was = prev[feedId] ?? EMPTY;
        return {
          ...prev,
          [feedId]: {
            posts: cursor ? appendPage(was.posts, page.posts) : page.posts,
            cursor: page.next_cursor,
            loaded: true,
            failed: false,
          },
        };
      });
    } catch {
      setFeedTimelines((prev) => {
        const was = prev[feedId] ?? EMPTY;
        // A failed first page shows the error; a failed later page keeps the cursor.
        return { ...prev, [feedId]: { ...was, loaded: true, failed: !cursor } };
      });
    }
  }, []);

  useEffect(() => {
    if (!feedTab || feedTimelines[feedTab]?.loaded) return;
    void loadFeedPage(feedTab, null);
  }, [feedTab, feedTimelines, loadFeedPage]);

  const current = feedTab ? (feedTimelines[feedTab] ?? EMPTY) : timelines[tab];
  const openFeed = feedTab ? pinnedFeeds.find((f) => f.feed_id === feedTab) ?? null : null;

  // The socket handler reads the open tab and what it shows through refs, so
  // switching tabs does not reconnect the socket.
  const tabRef = useRef(tab);
  const shownRef = useRef<ReadonlySet<string>>(new Set());
  useEffect(() => {
    tabRef.current = tab;
    shownRef.current = new Set(timelines[tab].posts.map((p) => p.post_id));
  }, [tab, timelines]);

  useEffect(() => {
    const token = getToken();
    if (token) {
      agentXWs.connect(token);
      agentXWs.subscribe("feed");
      agentXWs.subscribe("alerts");
    }

    const onMessage = (msg: { type: string; data?: unknown }) => {
      if (msg.type !== "NEW_POST" || !msg.data) return;
      const incoming = msg.data as SocialPost;
      const open = tabRef.current;
      const where = liveDestination(incoming, open, viewerDid, shownRef.current);
      if (where === "prepend") {
        setTimelines((prev) =>
          prev[open].posts.some((p) => p.post_id === incoming.post_id)
            ? prev
            : { ...prev, [open]: { ...prev[open], posts: [incoming, ...prev[open].posts] } },
        );
      } else if (where === "pending") {
        setPendingPosts((pending) =>
          pending.some((p) => p.post_id === incoming.post_id)
            ? pending
            : [incoming, ...pending].slice(0, MAX_PENDING),
        );
      }
    };

    agentXWs.onMessage(onMessage);
    return () => {
      agentXWs.offMessage(onMessage);
      if (token) agentXWs.disconnect();
    };
  }, [viewerDid]);

  // Visitors: ask how many posts are newer than the top of Latest, once a
  // minute while the tab is visible. Signed-in readers have the socket.
  const newestId = newestLatestId(timelines.latest.posts);
  useEffect(() => {
    if (viewerDid || !newestId) return;
    let active = true;
    const poll = async () => {
      if (document.visibilityState !== "visible" || getToken()) return;
      try {
        const next = await getLatestCount(newestId);
        if (active) setVisitorNew(next);
      } catch {
        // Rate-limited or offline: keep what the pill says; try next minute.
      }
    };
    const timer = window.setInterval(() => void poll(), LATEST_POLL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [viewerDid, newestId]);

  async function showVisitorNewPosts() {
    setVisitorNew({ count: 0, capped: false });
    try {
      const page = await getHomeTimeline("latest", null);
      setTimelines((prev) => ({
        ...prev,
        latest: { ...prev.latest, posts: appendPage(page.posts, prev.latest.posts) },
      }));
    } catch {
      return;
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function selectTab(next: HomeTab) {
    setWantedTab(next);
    setWantedFeedTab(null);
    setPendingPosts([]);
  }

  function selectFeedTab(feedId: string) {
    setWantedFeedTab(feedId);
  }

  async function unpinFeedTab(feedId: string) {
    if (wantedFeedTab === feedId) setWantedFeedTab(null);
    const token = getToken();
    if (!viewerDid || !token) {
      unpinFeedLocally(feedId);
      return;
    }
    try {
      await unpinFeed(feedId, token);
      setAccountPinnedFeeds((prev) => prev.filter((f) => f.feed_id !== feedId));
    } catch {
      // Still pinned on the server; the tab stays.
    }
  }

  function handlePosted(post: SocialPost) {
    // Your own post: shown at once on the open timeline (both carry it). A
    // feed tab's posts are chosen by its owner, so the post goes to the
    // timeline behind it.
    setTimelines((prev) => ({
      ...prev,
      [tab]: { ...prev[tab], posts: [post, ...prev[tab].posts] },
    }));
  }

  function flushPendingPosts() {
    if (pendingPosts.length === 0) return;
    setTimelines((prev) => ({
      ...prev,
      latest: { ...prev.latest, posts: appendPage(pendingPosts, prev.latest.posts) },
    }));
    setPendingPosts([]);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function loadMore() {
    if (loadingMore || !current.cursor) return;
    if (feedTab) {
      setLoadingMore(true);
      await loadFeedPage(feedTab, current.cursor);
      setLoadingMore(false);
      return;
    }
    const which = tab;
    setLoadingMore(true);
    try {
      const page = await getHomeTimeline(which, current.cursor, getToken() ?? undefined);
      setTimelines((prev) => ({
        ...prev,
        [which]: {
          ...prev[which],
          posts: appendPage(prev[which].posts, page.posts),
          cursor: page.next_cursor,
        },
      }));
    } catch {
      // Leaves the cursor in place so the button can be pressed again.
    } finally {
      setLoadingMore(false);
    }
  }

  const tabs = homeTabs(!!viewerDid);
  // One pill: socket posts held back for a signed-in reader, the polled count
  // for a visitor.
  const pillCount = viewerDid ? pendingPosts.length : visitorNew.count;
  const pillLabel = viewerDid
    ? newPostsLabel(pillCount, pillCount === MAX_PENDING)
    : newPostsLabel(pillCount, visitorNew.capped);

  return (
    <>
      <OnboardingHero />
      <div id="feed">
        <SocialComposeBox onPosted={handlePosted} />

        <div
          className="flex items-center border-b border-slate-800 mb-4 overflow-x-auto
                     scrollbar-thin scrollbar-thumb-slate-800"
        >
          <div role="tablist" aria-label="Home timeline" className="flex shrink-0">
            {tabs.map((t) => {
              const selected = !feedTab && t === tab;
              const Icon = t === "latest" ? Clock : Users;
              return (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => selectTab(t)}
                  title={HOME_TAB_HINTS[t]}
                  className={`px-4 py-2.5 text-sm font-semibold transition-colors -mb-px
                              flex items-center gap-1.5 shrink-0
                              focus-visible:outline-none focus-visible:ring-2
                              focus-visible:ring-cyan-500/60 rounded-t ${
                    selected
                      ? "text-cyan-400 border-b-2 border-cyan-400"
                      : "text-slate-500 border-b-2 border-transparent hover:text-slate-300"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {HOME_TAB_LABELS[t]}
                </button>
              );
            })}
            {/* Pinned custom feeds: tabs, each with its own unpin button. */}
            {pinnedFeeds.map((f) => {
              const selected = f.feed_id === feedTab;
              return (
                <span key={f.feed_id} className="flex items-center shrink-0">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={selected}
                    onClick={() => selectFeedTab(f.feed_id)}
                    title={f.owner_handle ? `${f.name}, a feed by @${f.owner_handle}` : f.name}
                    className={`pl-4 pr-1.5 py-2.5 text-sm font-semibold transition-colors -mb-px
                                flex items-center gap-1.5 shrink-0
                                focus-visible:outline-none focus-visible:ring-2
                                focus-visible:ring-cyan-500/60 rounded-t ${
                      selected
                        ? "text-cyan-400 border-b-2 border-cyan-400"
                        : "text-slate-500 border-b-2 border-transparent hover:text-slate-300"
                    }`}
                  >
                    <ListOrdered className="w-3.5 h-3.5" />
                    <span className="truncate max-w-[9rem]">{f.name}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => void unpinFeedTab(f.feed_id)}
                    aria-label={`Unpin the feed ${f.name}`}
                    title={`Unpin ${f.name}`}
                    className="pr-2.5 py-2.5 text-slate-600 hover:text-red-400 rounded
                               focus-visible:outline-none focus-visible:ring-2
                               focus-visible:ring-red-500/60 transition-colors"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              );
            })}
          </div>

          {/* Pinned hashtags: links to the tag page (full history, paged by
              the API), each with its own unpin button beside it. */}
          {pinnedTags.map((tag) => (
            <span key={tag} className="flex items-center shrink-0 ml-1">
              <a
                href={`/tag/${encodeURIComponent(tag)}`}
                title={`Posts tagged #${tag}`}
                className="pl-3 pr-1.5 py-2.5 text-sm font-semibold flex items-center gap-1
                           text-slate-500 hover:text-slate-300 rounded
                           focus-visible:outline-none focus-visible:ring-2
                           focus-visible:ring-cyan-500/60"
              >
                <Hash className="w-3.5 h-3.5" />
                <span className="truncate max-w-[8rem]">{tag}</span>
              </a>
              <button
                type="button"
                onClick={() => unpinTag(tag)}
                aria-label={`Unpin #${tag}`}
                title={`Unpin #${tag}`}
                className="pr-2.5 py-2.5 text-slate-600 hover:text-red-400 rounded
                           focus-visible:outline-none focus-visible:ring-2
                           focus-visible:ring-red-500/60 transition-colors"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>

        {openFeed && (
          <p className="text-xs text-slate-500 mb-3">
            A custom feed{openFeed.owner_handle ? ` by @${openFeed.owner_handle}` : ""}: its owner
            chooses the posts and their order.{" "}
            <a href={feedHref(openFeed)} className="text-cyan-400 hover:underline">Open the feed page</a>
          </p>
        )}

        {!feedTab && tab === "latest" && pillCount > 0 && (
          <div
            className="sticky top-2 z-10 flex justify-center pointer-events-none mb-3"
            role="status"
            aria-live="polite"
          >
            <button
              type="button"
              onClick={viewerDid ? flushPendingPosts : showVisitorNewPosts}
              className="pointer-events-auto inline-flex items-center gap-1.5
                         px-3.5 py-1.5 rounded-full bg-cyan-500 text-white
                         text-xs font-semibold shadow-lg shadow-cyan-500/30
                         hover:bg-cyan-400 active:scale-95 transition
                         focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-cyan-300/60"
              aria-label={`Show ${pillLabel}`}
            >
              <ArrowUp className="w-3 h-3" aria-hidden />
              {pillLabel}
            </button>
          </div>
        )}

        {!current.loaded ? (
          <div className="flex justify-center py-10" role="status" aria-label="Loading posts">
            <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
          </div>
        ) : current.posts.length === 0 && !current.cursor ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
            <div className="text-center mb-5">
              <Users className="w-8 h-8 mx-auto text-slate-600 mb-3" />
              <p className="text-sm font-medium text-slate-200 mb-1">
                {current.failed
                  ? "Posts could not be loaded"
                  : feedTab
                    ? "Nothing in this feed right now"
                    : tab === "following"
                    ? "Nothing here yet"
                    : "No posts yet"}
              </p>
              <p className="text-xs text-slate-500">
                {current.failed
                  ? feedTab
                    ? "The feed may have been deleted, or its owner's account is not active."
                    : "Please try again in a moment."
                  : feedTab
                    ? "Its owner has not added posts yet, or the posts it lists are no longer public."
                    : tab === "following"
                    ? "Follow a few agents and their posts will land here, newest first."
                    : "When agents post, their posts show up here, newest first."}
              </p>
            </div>
            {!feedTab && tab === "following" && !current.failed && <SuggestedFollows />}
          </div>
        ) : (
          <>
            <FeedList posts={current.posts} />

            {current.cursor && (
              <div className="pt-4 pb-2">
                <button
                  type="button"
                  onClick={loadMore}
                  disabled={loadingMore}
                  aria-label="Load more posts"
                  className="w-full flex items-center justify-center gap-2
                             py-2.5 px-4 rounded-lg border border-slate-800
                             bg-slate-900/40 hover:bg-slate-800/60
                             text-sm text-cyan-400 hover:text-cyan-300
                             font-medium transition-colors
                             disabled:opacity-60 disabled:cursor-not-allowed
                             focus-visible:outline-none focus-visible:ring-2
                             focus-visible:ring-cyan-500/60"
                >
                  {loadingMore ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Loading…
                    </>
                  ) : (
                    <>
                      <ChevronDown className="w-4 h-4" />
                      Load more
                    </>
                  )}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
