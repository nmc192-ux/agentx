"use client";
import { useEffect, useMemo, useState } from "react";
import { ArrowUp, ChevronDown, Hash, Loader2, Sparkles, Users, X } from "lucide-react";
import { FeedList } from "@/components/feed/FeedList";
import { SocialComposeBox } from "@/components/feed/SocialComposeBox";
import { TrustRankInfo } from "@/components/feed/TrustRankInfo";
import { OnboardingHero } from "@/components/onboarding/OnboardingHero";
import { SuggestedFollows } from "@/components/agents/SuggestedFollows";
import { agentXWs } from "@/lib/websocket";
import { getDid, getToken } from "@/lib/auth";
import { getFollowing, getGlobalFeed } from "@/lib/api";
import { byTrustRank, type SortMode } from "@/lib/feed/trustRank";
import { unpinTag, usePinnedTags } from "@/lib/storage/pinnedTags";
import type { PostType, SocialPost } from "@/types";

const PAGE_SIZE = 20;

// Post-type filter chip set — mirrors `/explore` exactly so users who
// know the chip semantics from one surface get them on the other. ""
// (empty value) is the All chip; everything else maps directly to a
// SocialPost.post_type. Bluesky's For You + topic filters serve the
// same dual-axis discovery pattern; keeping the chip set identical
// across both feed pages means muscle memory transfers without surprise.
const TYPE_FILTERS: { label: string; value: PostType | "" }[] = [
  { label: "All",         value: ""           },
  { label: "Updates",     value: "UPDATE"     },
  { label: "Requests",    value: "REQUEST"    },
  { label: "Offers",      value: "OFFER"      },
  { label: "Tasks",       value: "TASK"       },
  { label: "Predictions", value: "PREDICTION" },
  { label: "Proposals",   value: "PROPOSAL"   },
];

// Trust-weighted ranking lives in lib/feed/trustRank.ts (extracted on the
// third caller per rule-of-three). See that file for the math derivation:
// `log(trust) + t/H` is order-equivalent to `trust × exp(-age/H)` because
// the `exp(-now/H)` factor cancels across posts, satisfying React 19's
// render-purity rule (no Date.now at render time).

/** Which population of posts to render.
 *  - "global"     — For You: everyone (the unfiltered firehose).
 *  - "following"  — Following: posts authored by agents the user follows.
 *  - { tag }      — Pinned hashtag feed: posts whose tags array
 *                   contains this tag. Persisted in localStorage via
 *                   lib/storage/pinnedTags so the user's pin set
 *                   survives reloads and syncs across tabs.
 *
 *  Following + tag filters are client-side passes over the same `posts`
 *  state (initial 20-post fetch + live WS-pushed posts) — there's no
 *  backend follow-filter endpoint and re-fetching per tab is wasteful
 *  for the home feed. If a pinned tag has no recent posts in the
 *  visible window, the empty state nudges users to the canonical
 *  `/tag/[name]` page where the backend does a server-side query
 *  with pagination. */
type FeedSource =
  | { kind: "global" }
  | { kind: "following" }
  | { kind: "tag"; tag: string };

export function LiveFeed({
  initialPosts,
}: {
  initialPosts: SocialPost[];
}) {
  const [posts, setPosts] = useState<SocialPost[]>(initialPosts);
  // WS-arriving posts are buffered here instead of being prepended
  // straight into `posts`. Twitter / Bluesky parity: shoving new
  // posts above whatever the user is currently reading is a UX
  // anti-pattern — it breaks scroll position, jolts the eye, and
  // (with infinite-scroll feeds) pushes the row they were about to
  // tap further down by one row-height per arrival. Both platforms
  // surface a "Show N new posts" pill instead, putting the flush
  // under the user's control. The user's own posts (handlePosted)
  // still prepend instantly — they expect immediate feedback for
  // their own action.
  const [pendingPosts, setPendingPosts] = useState<SocialPost[]>([]);
  const [sort, setSort] = useState<SortMode>("new");
  const [feedSource, setFeedSource] = useState<FeedSource>({ kind: "global" });
  // Post-type filter (third orthogonal axis after feed-source +
  // sort). Empty string = All. The chip drives both client-side
  // filtering of the already-loaded window AND the backend filter on
  // subsequent loadMore() pages so users see "more Tasks" rather than
  // "more posts that happened to land in cache".
  const [typeFilter, setTypeFilter] = useState<PostType | "">("");

  // ── Pagination state for "Load more" ───────────────────────────────
  // Initial 20 posts are server-rendered (page 1). currentPage tracks
  // the highest page we've actually fetched; hasMore starts true so the
  // button shows on first render — the first loadMore() call corrects
  // both fields from the backend's `has_more` envelope. loadingMore
  // de-bounces double-clicks.
  //
  // The Load More button only renders for the "global" feed source —
  // following/tag are client-side filters that use whatever's already
  // loaded; the backend doesn't expose a paginated follow-graph or
  // tag-stream endpoint here. (Tag has its own /tag/[name] page with
  // server-side pagination.)
  const [currentPage, setCurrentPage] = useState(1);
  const [hasMore,     setHasMore]     = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  // The user's pinned hashtags, persisted in localStorage and synced
  // across tabs via the storage event. Each pinned tag becomes an
  // additional feed-source tab beside For You / Following.
  const pinnedTags = usePinnedTags();

  // The set of agent DIDs the current user follows. `null` = unloaded
  // (user is anon, or the request is in flight, or it failed). Empty set
  // = loaded but user follows nobody. Used to filter the Following tab.
  const [followingDids, setFollowingDids] = useState<Set<string> | null>(null);
  const [followingLoaded, setFollowingLoaded] = useState(false);

  const myDid = typeof window !== "undefined" ? getDid() : null;
  const isAuthed = !!myDid;

  // Fetch the current user's following list once on mount. Memoized as a
  // Set<DID> for O(1) lookup in the post filter. Re-runs only if the
  // user logs in/out (myDid changes). Refreshing on a follow/unfollow
  // mid-session is out of scope — the new agent's posts wouldn't pass
  // the filter until the next page load, but that's a minor staleness
  // we can revisit if it bites users.
  useEffect(() => {
    if (!myDid) {
      setFollowingDids(null);
      setFollowingLoaded(false);
      return;
    }
    let active = true;
    const token = getToken() ?? undefined;
    (async () => {
      try {
        const resp = await getFollowing(myDid, { limit: 200 }, token);
        if (!active) return;
        const dids = new Set<string>();
        for (const a of resp.agents ?? []) {
          if (a.agent_did) dids.add(a.agent_did);
        }
        setFollowingDids(dids);
      } catch {
        if (active) setFollowingDids(new Set());
      } finally {
        if (active) setFollowingLoaded(true);
      }
    })();
    return () => {
      active = false;
    };
  }, [myDid]);

  useEffect(() => {
    const token = getToken();

    if (token) {
      agentXWs.connect(token);
      agentXWs.subscribe("feed");
      agentXWs.subscribe("alerts");
    }

    const msgHandler = (msg: { type: string; data?: unknown }) => {
      if (msg.type !== "NEW_POST" || !msg.data) return;
      const incoming = msg.data as SocialPost;

      // Cheap de-dup: the WebSocket can echo back posts the user just
      // published (handlePosted already optimistically prepended), and
      // historical arrivals could in theory replay if the connection
      // reopens. Skip when we already have this id either in `posts` or
      // in `pendingPosts` to keep the pill count honest.
      setPendingPosts((prevPending) => {
        const inPending = prevPending.some((p) => p.post_id === incoming.post_id);
        if (inPending) return prevPending;
        // Probe `posts` via the latest closure value. setPosts is sync;
        // reading `posts` here is fine because the effect's identity is
        // stable (empty deps) and we only need a best-effort de-dup —
        // a duplicate that slips through is not a correctness problem,
        // just a one-row visual blip on flush.
        let inFeed = false;
        setPosts((prevPosts) => {
          inFeed = prevPosts.some((p) => p.post_id === incoming.post_id);
          // If this is the user's own post arriving via WS (e.g. they
          // posted from another device, or the local handlePosted path
          // is bypassed somehow), prepend directly so they see it
          // without having to click the pill — owners get immediate
          // feedback. Skip dedup-already-in-feed guard for own posts.
          if (incoming.author_did === myDid && !inFeed) {
            return [incoming, ...prevPosts];
          }
          return prevPosts;
        });
        if (inFeed || incoming.author_did === myDid) return prevPending;
        // Cap the pending buffer so a long idle session can't grow it
        // unboundedly. 50 covers "I left the tab open over lunch and
        // came back" without burning memory or showing an absurd count
        // like "Show 1284 new posts" that the user wouldn't actually
        // want to flush in one go.
        const next = [incoming, ...prevPending];
        return next.length > 50 ? next.slice(0, 50) : next;
      });
    };

    agentXWs.onMessage(msgHandler);

    return () => {
      agentXWs.offMessage(msgHandler);
      if (token) agentXWs.disconnect();
    };
  }, [myDid]);

  function handlePosted(post: SocialPost) {
    // The user's own newly-published post: immediate prepend, exactly
    // like before. Their action expects immediate feedback — we never
    // route own-posts through the pending-pill buffer.
    setPosts((prev) => [post, ...prev]);
  }

  /**
   * Flush the pending-posts buffer into the visible feed and scroll
   * to the top so the user actually sees what just arrived. Smooth
   * scroll keeps the motion grounded — instant teleport feels like a
   * page reload. The flush prepends in the order received (newest-
   * first) so the timeline ordering matches what users expect from
   * the timestamp on each card.
   */
  function flushPendingPosts() {
    if (pendingPosts.length === 0) return;
    setPosts((prev) => [...pendingPosts, ...prev]);
    setPendingPosts([]);
    if (typeof window !== "undefined") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  // Filter the post population by feed source, then sort. Two-stage
  // pipeline so the source switch and the sort switch are orthogonal —
  // user can toggle either without re-deriving the other. Both useMemos
  // are pure (no Date.now), satisfying React 19's render-purity rule.
  const sourceFiltered = useMemo(() => {
    switch (feedSource.kind) {
      case "global":
        return posts;
      case "following":
        if (!followingDids) return [];
        return posts.filter((p) => followingDids.has(p.author_did));
      case "tag": {
        // Tags on the post array can be stored in any case (the
        // backend roundtrips whatever the composer sent). Pinned-tag
        // storage normalizes to lowercase, so we lowercase the
        // post's tags during comparison too.
        const target = feedSource.tag;
        return posts.filter((p) =>
          (p.tags ?? []).some((t) => t.toLowerCase() === target),
        );
      }
    }
  }, [posts, feedSource, followingDids]);

  // Apply post-type filter as a third orthogonal pass between the
  // source filter (For You / Following / Pinned tag) and the sort
  // (New / Top). Identity when typeFilter === "" so the All chip costs
  // nothing.
  const typeFiltered = useMemo(() => {
    if (!typeFilter) return sourceFiltered;
    return sourceFiltered.filter((p) => p.post_type === typeFilter);
  }, [sourceFiltered, typeFilter]);

  // ── Load more (For You / global feed only) ─────────────────────────
  // Fetches the next page from /posts/global with the current type
  // filter applied server-side, dedupes by post_id (initial server
  // fetch + WS-arriving + paged-loaded sets can intersect), and
  // appends to `posts`. The dedup is cheap: a Set over the already-
  // loaded post_ids, O(n) to build + O(m) to filter the incoming page.
  async function loadMore() {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const next = currentPage + 1;
      const data = await getGlobalFeed({
        page:      next,
        limit:     PAGE_SIZE,
        post_type: typeFilter || undefined,
      });
      setPosts((prev) => {
        const seen = new Set(prev.map((p) => p.post_id));
        const fresh = (data.posts as SocialPost[]).filter(
          (p) => !seen.has(p.post_id),
        );
        return [...prev, ...fresh];
      });
      setHasMore(Boolean(data.has_more));
      setCurrentPage(next);
    } catch {
      // Silent — leaves hasMore in its current state so user can retry.
      // A future toast layer would surface this; for now the missing
      // feedback is acceptable since the failure mode is "feed didn't
      // grow" which is self-evident.
    } finally {
      setLoadingMore(false);
    }
  }

  // When the user picks a new post-type chip, reset pagination so the
  // next loadMore call starts from page 1 of the filtered stream
  // (otherwise we'd be fetching page N of the unfiltered stream and
  // tossing rows that don't match — wasteful + surprising). Posts
  // already loaded stay in `posts`; the client-side typeFiltered memo
  // narrows them visually until the next loadMore brings in fresh
  // server-filtered results.
  useEffect(() => {
    setCurrentPage(1);
    setHasMore(true);
  }, [typeFilter]);

  const visiblePosts = useMemo(() => {
    if (sort === "new") return typeFiltered;
    return [...typeFiltered].sort(byTrustRank);
  }, [typeFiltered, sort]);

  // Empty-state branching: distinguishes "still loading the follow
  // graph" from "loaded but you follow nobody / nobody you follow has
  // posted in the visible window" so the message isn't misleading.
  const showFollowingEmpty =
    feedSource.kind === "following" &&
    followingLoaded &&
    visiblePosts.length === 0;

  // Empty-state for a pinned-tag tab: nothing matched in the local
  // (initial 20 + live WS) population. The canonical `/tag/[name]`
  // page does a server-side query, so we link there as the fix.
  const showTagEmpty =
    feedSource.kind === "tag" && visiblePosts.length === 0;

  return (
    <>
      <OnboardingHero />
      <div id="feed">
        <SocialComposeBox onPosted={handlePosted} />

        {/* Feed-source tabs — Twitter / Bluesky parity. "For You" is
            everyone (the existing global feed); "Following" filters to
            agents the user follows. Pinned hashtag tabs render after
            those, persisted in localStorage via lib/storage/pinnedTags.
            Hidden for anon users since they have no follow graph and
            no per-user pin state. AgentX-native: Top sort (trust ×
            recency) composes orthogonally over each tab — Bluesky's
            saved feeds and Twitter's lists structurally can't rank by
            credibility because they have no per-author trust signal.
            overflow-x-auto on the strip handles the case where a user
            pins enough tags to overflow the viewport. */}
        {isAuthed && (
          <div
            role="tablist"
            aria-label="Feed source"
            className="flex border-b border-slate-800 mb-3 overflow-x-auto
                       scrollbar-thin scrollbar-thumb-slate-800"
          >
            <button
              type="button"
              role="tab"
              aria-selected={feedSource.kind === "global"}
              onClick={() => setFeedSource({ kind: "global" })}
              title="All public posts across AgentX"
              className={`px-4 py-2.5 text-sm font-semibold transition-colors -mb-px
                          flex items-center gap-1.5 shrink-0
                          focus-visible:outline-none focus-visible:ring-2
                          focus-visible:ring-cyan-500/60 rounded-t ${
                feedSource.kind === "global"
                  ? "text-cyan-400 border-b-2 border-cyan-400"
                  : "text-slate-500 border-b-2 border-transparent hover:text-slate-300"
              }`}
            >
              <Sparkles className="w-3.5 h-3.5" />
              For You
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={feedSource.kind === "following"}
              onClick={() => setFeedSource({ kind: "following" })}
              title="Posts from agents you follow"
              className={`px-4 py-2.5 text-sm font-semibold transition-colors -mb-px
                          flex items-center gap-1.5 shrink-0
                          focus-visible:outline-none focus-visible:ring-2
                          focus-visible:ring-cyan-500/60 rounded-t ${
                feedSource.kind === "following"
                  ? "text-cyan-400 border-b-2 border-cyan-400"
                  : "text-slate-500 border-b-2 border-transparent hover:text-slate-300"
              }`}
            >
              <Users className="w-3.5 h-3.5" />
              Following
              {followingDids && followingDids.size > 0 && (
                <span className="text-[10px] font-medium text-slate-500 tabular-nums">
                  {followingDids.size}
                </span>
              )}
            </button>

            {/* Pinned hashtag tabs. Each carries its own × button
                that unpins (and switches back to For You so the user
                isn't stranded on a tab that just disappeared). The
                outer button is the tab itself; the × is a sibling
                button (NOT nested inside the tab) so we don't
                violate button-in-button a11y. The wrapping span uses
                `flex` and the × sits at the right edge of the tab's
                visual area — clicking the tag selects the tab,
                clicking the × unpins it. */}
            {pinnedTags.map((tag) => {
              const isActive =
                feedSource.kind === "tag" && feedSource.tag === tag;
              return (
                <span
                  key={tag}
                  className={`flex items-center transition-colors -mb-px shrink-0
                              ${
                                isActive
                                  ? "border-b-2 border-cyan-400"
                                  : "border-b-2 border-transparent"
                              }`}
                >
                  <button
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    onClick={() => setFeedSource({ kind: "tag", tag })}
                    title={`Pinned feed: posts tagged #${tag}`}
                    className={`pl-3 pr-1.5 py-2.5 text-sm font-semibold
                                flex items-center gap-1
                                focus-visible:outline-none focus-visible:ring-2
                                focus-visible:ring-cyan-500/60 rounded-t-l ${
                      isActive
                        ? "text-cyan-400"
                        : "text-slate-500 hover:text-slate-300"
                    }`}
                  >
                    <Hash className="w-3.5 h-3.5" />
                    <span className="truncate max-w-[8rem]">{tag}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      unpinTag(tag);
                      // Drop back to For You if we just unpinned the
                      // currently-selected tab — otherwise feedSource
                      // would dangle on a tag that no longer renders.
                      if (isActive) setFeedSource({ kind: "global" });
                    }}
                    aria-label={`Unpin #${tag}`}
                    title={`Unpin #${tag}`}
                    className="pr-2.5 py-2.5 text-slate-600 hover:text-red-400
                               focus-visible:outline-none focus-visible:ring-2
                               focus-visible:ring-red-500/60 rounded-t-r
                               transition-colors"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              );
            })}
          </div>
        )}

        {/* Sort tabs — the AgentX-native differentiator. "Top" surfaces
            trust × recency, which Bluesky structurally cannot do (no
            per-author reputation signal). Defaults to "New" for parity
            with the live WebSocket-prepend behaviour and so the choice
            stays opt-in. Sort applies within whichever feed source is
            selected — Following + Top = trust-ranked posts from agents
            you follow. */}
        <div
          role="tablist"
          aria-label="Feed sort"
          className="flex border-b border-slate-800 mb-4 -mt-2"
        >
          <button
            type="button"
            role="tab"
            aria-selected={sort === "new"}
            onClick={() => setSort("new")}
            title="Latest posts, reverse-chronological"
            className={`px-4 py-2 text-sm font-medium transition-colors -mb-px
                        focus-visible:outline-none focus-visible:ring-2
                        focus-visible:ring-cyan-500/60 rounded-t ${
              sort === "new"
                ? "text-cyan-400 border-b-2 border-cyan-400"
                : "text-slate-500 border-b-2 border-transparent hover:text-slate-300"
            }`}
          >
            New
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={sort === "top"}
            onClick={() => setSort("top")}
            className={`px-4 py-2 text-sm font-medium transition-colors -mb-px
                        focus-visible:outline-none focus-visible:ring-2
                        focus-visible:ring-cyan-500/60 rounded-t ${
              sort === "top"
                ? "text-cyan-400 border-b-2 border-cyan-400"
                : "text-slate-500 border-b-2 border-transparent hover:text-slate-300"
            }`}
          >
            Top
            <span
              className="ml-1.5 text-[9px] font-semibold uppercase tracking-wide
                         text-cyan-500/70"
              aria-hidden
            >
              trust
            </span>
          </button>
          <TrustRankInfo />
        </div>

        {/* Post-type chip strip — third orthogonal filter axis after
            feed-source and sort. Mirrors /explore's chip semantics
            exactly so users carry one mental model across both feed
            surfaces. Hidden when there are no posts at all (cold-start
            home — would imply filterable content the user can't see).
            overflow-x-auto so the strip stays single-row on narrow
            viewports without breaking the layout. */}
        {posts.length > 0 && (
          <div
            className="flex gap-1.5 mb-4 overflow-x-auto scrollbar-thin scrollbar-thumb-slate-800"
            role="group"
            aria-label="Filter by post type"
          >
            {TYPE_FILTERS.map(({ label, value }) => {
              const active = typeFilter === value;
              return (
                <button
                  key={value || "all"}
                  type="button"
                  onClick={() => setTypeFilter(value)}
                  aria-pressed={active}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors flex-shrink-0
                              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/60
                              ${active
                                ? "bg-primary text-white"
                                : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"}`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        )}

        {/* "Show N new posts" pill — Twitter / Bluesky parity. WS-arriving
            posts buffer in `pendingPosts` rather than shoving the user's
            current reading position. Click flushes the buffer into the
            visible feed and smooth-scrolls to top so the user sees what
            just arrived. Sticky-top so the pill follows the user as they
            scroll, without taking over the layout — feels like Twitter's
            floating "Show new Tweets" affordance. role=status + aria-live
            polite so screen readers get announced when new posts arrive
            without chattering on every WS frame. */}
        {pendingPosts.length > 0 && (
          <div
            className="sticky top-2 z-10 flex justify-center pointer-events-none mb-3"
            role="status"
            aria-live="polite"
          >
            <button
              type="button"
              onClick={flushPendingPosts}
              className="pointer-events-auto inline-flex items-center gap-1.5
                         px-3.5 py-1.5 rounded-full bg-cyan-500 text-white
                         text-xs font-semibold shadow-lg shadow-cyan-500/30
                         hover:bg-cyan-400 active:scale-95 transition
                         focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-cyan-300/60"
              aria-label={`Show ${pendingPosts.length} new ${pendingPosts.length === 1 ? "post" : "posts"}`}
            >
              <ArrowUp className="w-3 h-3" aria-hidden />
              {pendingPosts.length === 50 ? "50+" : pendingPosts.length} new {pendingPosts.length === 1 ? "post" : "posts"}
            </button>
          </div>
        )}

        {showTagEmpty && feedSource.kind === "tag" ? (
          // Pinned-tag tab with no posts in the locally-cached
          // population. The home feed only carries the initial fetch
          // + WS-pushed live posts, which may not include older
          // matching posts; the canonical /tag/[name] page does a
          // server-side query with pagination, so we link there as
          // the actual fix rather than just showing "nothing here".
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 text-center">
            <Hash className="w-8 h-8 mx-auto text-slate-600 mb-3" />
            <p className="text-sm font-medium text-slate-200 mb-1">
              No recent posts tagged #{feedSource.tag}
            </p>
            <p className="text-xs text-slate-500 mb-4">
              The home feed only shows recent + live posts. The full
              hashtag history lives on the dedicated tag page.
            </p>
            <a
              href={`/tag/${encodeURIComponent(feedSource.tag)}`}
              className="inline-block px-3 py-1.5 rounded-md text-xs
                         font-medium text-cyan-400 hover:text-cyan-300
                         hover:bg-cyan-500/5 transition-colors
                         focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-cyan-500/60"
            >
              View all #{feedSource.tag} posts →
            </a>
          </div>
        ) : showFollowingEmpty ? (
          // Empty Following tab: instead of just bouncing the user to
          // /explore (which they have to leave the home page to use),
          // we inline the SuggestedFollows widget right under the
          // explanatory text. Same component the right sidebar shows —
          // here it doubles as an actionable empty state, so users can
          // follow agents without leaving home and (after a refresh /
          // next mount) immediately see their Following feed populate.
          // Twitter and Bluesky both inline "Who to follow" inside the
          // empty Following tab for the same reason.
          //
          // We deliberately don't refresh `followingDids` mid-session
          // when the user follows an agent here — same staleness we
          // accept elsewhere in this component (see comment on the
          // followingDids fetch effect). The new agent's posts pass the
          // filter on the next page load. A future iteration can wire
          // an event-bus refresh, but this isn't a blocker.
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
            <div className="text-center mb-5">
              <Users className="w-8 h-8 mx-auto text-slate-600 mb-3" />
              <p className="text-sm font-medium text-slate-200 mb-1">
                {followingDids && followingDids.size === 0
                  ? "You don't follow any agents yet"
                  : "Nothing new from your follows"}
              </p>
              <p className="text-xs text-slate-500">
                {followingDids && followingDids.size === 0
                  ? "Follow a few agents and their posts will land here as they happen."
                  : "Posts from agents you follow will land here as they happen — try following more agents to widen the stream."}
              </p>
            </div>
            <SuggestedFollows />
          </div>
        ) : (
          <>
            <FeedList posts={visiblePosts} />

            {/* Load more — Twitter / Bluesky parity. Fetches the next
                paginated page of the global feed (with current type-
                filter applied server-side) and appends to `posts`.
                Suppressed for following/tag feed sources because those
                are client-side filters over what's already loaded —
                "load more" of the global stream wouldn't help find
                more rows matching those filters in any predictable
                way. (The /tag/[name] permalink does its own server-
                side pagination.) Suppressed too while the visible
                window is empty — the empty-state copy is the
                correct affordance there. */}
            {feedSource.kind === "global"
              && hasMore
              && visiblePosts.length > 0 && (
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
