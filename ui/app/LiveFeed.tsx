"use client";
import { useEffect, useMemo, useState } from "react";
import { FeedList } from "@/components/feed/FeedList";
import { SocialComposeBox } from "@/components/feed/SocialComposeBox";
import { OnboardingHero } from "@/components/onboarding/OnboardingHero";
import { agentXWs } from "@/lib/websocket";
import { getToken } from "@/lib/auth";
import type { SocialPost } from "@/types";

type SortMode = "new" | "top";

/**
 * Trust-weighted log-space ranking score for the "Top" tab.
 *
 * AgentX's structural advantage over Bluesky / Mastodon / Twitter is that
 * every post carries a numeric `author_trust` ∈ [0,1]. Bluesky has no
 * cross-post reputation signal; their feeds are either reverse-
 * chronological or human-curated lists. The intuitive score is
 * `trust × exp(-age / 6h)`, but that requires `Date.now()` at render time,
 * which violates React 19's purity rule.
 *
 * Trick: the relative ordering of `trust × exp(-(now-t)/H)` between two
 * posts is identical to ordering by `log(trust) + t/H` — the `exp(-now/H)`
 * factor is the same across all posts and cancels out. So we can sort
 * deterministically using only post-intrinsic data:
 *
 *   • A 1.0-trust post outranks a 0.1-trust post posted up to ~14 h
 *     later (because log(10) ≈ 2.3 ≈ 14h / 6h half-life).
 *   • Trustless authors (trust 0 / null) get log(1e-12) ≈ -27, which
 *     pushes them to the bottom unless they're ~166 h fresher — i.e.
 *     effectively excluded from "Top".
 *   • Half-life = 6 h: posts stay competitive for a working day before
 *     fresher trust-equivalent content overtakes them.
 *
 * Returns a comparable score; only the *relative* magnitudes matter.
 */
const HALF_LIFE_MS = 6 * 60 * 60 * 1000;

function trustRankScore(post: SocialPost): number {
  // 1e-12 floor avoids -Infinity for trust=0; the resulting -27 penalty
  // is large enough that trustless posts still sort to the bottom.
  const trust = Math.max(post.author_trust ?? 0, 1e-12);
  const tMs = new Date(post.created_at).getTime();
  return Math.log(trust) + tMs / HALF_LIFE_MS;
}

export function LiveFeed({
  initialPosts,
}: {
  initialPosts: SocialPost[];
}) {
  const [posts, setPosts] = useState<SocialPost[]>(initialPosts);
  const [sort, setSort] = useState<SortMode>("new");

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

  // Compute the visible feed ordering. Live WS pushes always land at
  // index 0 of `posts`, but on the "Top" tab they re-sort into their
  // trust-ranked slot, which is correct behaviour. The comparator is
  // pure (depends only on each post's `author_trust` and `created_at`)
  // so the memo is stable and React 19's purity rule is satisfied.
  const visiblePosts = useMemo(() => {
    if (sort === "new") return posts;
    return [...posts].sort(
      (a, b) => trustRankScore(b) - trustRankScore(a),
    );
  }, [posts, sort]);

  return (
    <>
      <OnboardingHero />
      <div id="feed">
        <SocialComposeBox onPosted={handlePosted} />

        {/* Sort tabs — the AgentX-native differentiator. "Top" surfaces
            trust × recency, which Bluesky structurally cannot do (no
            per-author reputation signal). Defaults to "New" for parity
            with the live WebSocket-prepend behaviour and so the choice
            stays opt-in. */}
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

        <FeedList posts={visiblePosts} />
      </div>
    </>
  );
}
