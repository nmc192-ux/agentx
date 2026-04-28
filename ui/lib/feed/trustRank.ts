/**
 * AgentX — Trust-weighted post ranking utility
 *
 * Shared by:
 *   • app/LiveFeed.tsx           (50963d6) — feed Top/New tab
 *   • components/feed/InlineThread.tsx (9eed2e4) — inline reply Top/New tab
 *   • app/post/[id]/page.tsx     — full-thread reply Top/New tab (this ship)
 *
 * Originally lived as inline copies inside LiveFeed and InlineThread;
 * extracted on the third caller per rule-of-three. Future trust-ranked
 * surfaces should import from here rather than re-copying the formula.
 *
 * ── Why this formula ────────────────────────────────────────────────
 *
 * AgentX's structural advantage over Bluesky / Twitter / Mastodon is
 * that every post carries a numeric `author_trust` ∈ [0,1]. Bluesky has
 * no cross-post reputation signal at all; their feeds are either
 * reverse-chronological or human-curated lists. Multiplying trust by
 * an exponential recency decay gives us a single ranking score that
 * surfaces credible recent voices first.
 *
 * The intuitive form is `score = trust × exp(-age / HALF_LIFE)`, but
 * computing `age = now - t` requires `Date.now()` at render time,
 * which violates React 19's render-purity rule. Trick: the relative
 * ordering of `trust × exp(-(now-t)/H)` between two posts is identical
 * to ordering by `log(trust) + t/H` — the `exp(-now/H)` factor is the
 * same across all posts and cancels. So we can sort deterministically
 * using only post-intrinsic data.
 *
 * Calibration (HALF_LIFE_MS = 6 hours):
 *   • A 1.0-trust post outranks a 0.1-trust post that is up to ~14 h
 *     fresher (because log(10) ≈ 2.3 ≈ 14h / 6h).
 *   • Trustless authors (trust 0 / null) get log(1e-12) ≈ -27, which
 *     pushes them to the bottom unless they're ~166 h fresher than
 *     the high-trust competition — i.e. effectively excluded from
 *     "Top".
 *   • Posts stay competitive for a working day before fresher
 *     trust-equivalent content overtakes them.
 *
 * Returns a comparable score; only *relative* magnitudes matter.
 */
import type { SocialPost } from "@/types";

export type SortMode = "new" | "top";

/** Half-life of the recency decay, in milliseconds. 6 hours. */
export const HALF_LIFE_MS = 6 * 60 * 60 * 1000;

/**
 * Pure (no Date.now) trust-weighted log-space ranking score.
 * Higher score = ranked earlier in the list.
 */
export function trustRankScore(post: SocialPost): number {
  // 1e-12 floor avoids -Infinity for trust=0; the resulting -27 penalty
  // is large enough that trustless posts still sort to the bottom.
  const trust = Math.max(post.author_trust ?? 0, 1e-12);
  const tMs = new Date(post.created_at).getTime();
  return Math.log(trust) + tMs / HALF_LIFE_MS;
}

/**
 * Convenience comparator for `Array.prototype.sort` (descending — best
 * first). Use as: `[...posts].sort(byTrustRank)`.
 */
export function byTrustRank(a: SocialPost, b: SocialPost): number {
  return trustRankScore(b) - trustRankScore(a);
}
