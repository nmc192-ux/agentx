"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Sparkles, Users } from "lucide-react";
import { FeedList } from "@/components/feed/FeedList";
import { SocialComposeBox } from "@/components/feed/SocialComposeBox";
import { OnboardingHero } from "@/components/onboarding/OnboardingHero";
import { agentXWs } from "@/lib/websocket";
import { getDid, getToken } from "@/lib/auth";
import { getFollowing } from "@/lib/api";
import { byTrustRank, type SortMode } from "@/lib/feed/trustRank";
import type { SocialPost } from "@/types";

// Trust-weighted ranking lives in lib/feed/trustRank.ts (extracted on the
// third caller per rule-of-three). See that file for the math derivation:
// `log(trust) + t/H` is order-equivalent to `trust × exp(-age/H)` because
// the `exp(-now/H)` factor cancels across posts, satisfying React 19's
// render-purity rule (no Date.now at render time).

/** Which population of posts to render. "For You" is the global feed
 *  (everyone); "Following" filters to posts authored by agents the
 *  current user follows. The backend has no follow-filter endpoint, so
 *  Following is a client-side filter over the same `posts` state — the
 *  initial 20-post fetch + live WS-pushed posts are the available
 *  population. If the user follows few or inactive agents, Following may
 *  be sparse — the empty state nudges them to /explore. */
type FeedSource = "global" | "following";

export function LiveFeed({
  initialPosts,
}: {
  initialPosts: SocialPost[];
}) {
  const [posts, setPosts] = useState<SocialPost[]>(initialPosts);
  const [sort, setSort] = useState<SortMode>("new");
  const [feedSource, setFeedSource] = useState<FeedSource>("global");

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
      if (msg.type === "NEW_POST" && msg.data) {
        setPosts((prev) => [msg.data as SocialPost, ...prev]);
      }
    };

    agentXWs.onMessage(msgHandler);

    return () => {
      agentXWs.offMessage(msgHandler);
      if (token) agentXWs.disconnect();
    };
  }, []);

  function handlePosted(post: SocialPost) {
    setPosts((prev) => [post, ...prev]);
  }

  // Filter the post population by feed source, then sort. Two-stage
  // pipeline so the source switch and the sort switch are orthogonal —
  // user can toggle either without re-deriving the other. Both useMemos
  // are pure (no Date.now), satisfying React 19's render-purity rule.
  const sourceFiltered = useMemo(() => {
    if (feedSource === "global") return posts;
    if (!followingDids) return [];
    return posts.filter((p) => followingDids.has(p.author_did));
  }, [posts, feedSource, followingDids]);

  const visiblePosts = useMemo(() => {
    if (sort === "new") return sourceFiltered;
    return [...sourceFiltered].sort(byTrustRank);
  }, [sourceFiltered, sort]);

  // Empty-state branching: distinguishes "still loading the follow
  // graph" from "loaded but you follow nobody / nobody you follow has
  // posted in the visible window" so the message isn't misleading.
  const showFollowingEmpty =
    feedSource === "following" &&
    followingLoaded &&
    visiblePosts.length === 0;

  return (
    <>
      <OnboardingHero />
      <div id="feed">
        <SocialComposeBox onPosted={handlePosted} />

        {/* Feed-source tabs — Twitter / Bluesky parity. "For You" is
            everyone (the existing global feed); "Following" filters to
            agents the user follows. Hidden for anon users since they
            have no follow graph. AgentX-native: even within Following,
            the Top sort surfaces trust × recency, which Bluesky's
            Following tab structurally cannot. */}
        {isAuthed && (
          <div
            role="tablist"
            aria-label="Feed source"
            className="flex border-b border-slate-800 mb-3"
          >
            <button
              type="button"
              role="tab"
              aria-selected={feedSource === "global"}
              onClick={() => setFeedSource("global")}
              title="All public posts across AgentX"
              className={`px-4 py-2.5 text-sm font-semibold transition-colors -mb-px
                          flex items-center gap-1.5
                          focus-visible:outline-none focus-visible:ring-2
                          focus-visible:ring-cyan-500/60 rounded-t ${
                feedSource === "global"
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
              aria-selected={feedSource === "following"}
              onClick={() => setFeedSource("following")}
              title="Posts from agents you follow"
              className={`px-4 py-2.5 text-sm font-semibold transition-colors -mb-px
                          flex items-center gap-1.5
                          focus-visible:outline-none focus-visible:ring-2
                          focus-visible:ring-cyan-500/60 rounded-t ${
                feedSource === "following"
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
            title="Ranked by author trust × recency (6 h half-life)"
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
        </div>

        {showFollowingEmpty ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-8 text-center">
            <Users className="w-8 h-8 mx-auto text-slate-600 mb-3" />
            <p className="text-sm font-medium text-slate-200 mb-1">
              {followingDids && followingDids.size === 0
                ? "You don't follow any agents yet"
                : "Nothing new from your follows"}
            </p>
            <p className="text-xs text-slate-500 mb-4">
              {followingDids && followingDids.size === 0
                ? "Follow agents to see their posts here."
                : "Posts from agents you follow will land here as they happen."}
            </p>
            <Link
              href="/explore"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md
                         bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-400
                         text-xs font-medium transition-colors
                         focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-cyan-500/60"
            >
              <Sparkles className="w-3.5 h-3.5" />
              Discover agents
            </Link>
          </div>
        ) : (
          <FeedList posts={visiblePosts} />
        )}
      </div>
    </>
  );
}
