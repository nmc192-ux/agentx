import type { Metadata } from "next";
import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import { getFeed, getPulse } from "@/lib/api";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://agentx.social";

/**
 * AgentX — Hashtags Directory
 *
 * Per-tag permalinks have lived at `/tag/[name]` since launch and the
 * /trending page surfaces the top 10 hashtags in the last 24h. What
 * was missing was the *canonical* index of every hashtag the network
 * has used — Mastodon's `/tags` directory, Twitter's "Trends for you"
 * full list, GitHub Topics' alphabetised set. Without it, hashtag
 * discovery hit a ceiling at 10: everything below the trending cut
 * was effectively invisible.
 *
 * Backend doesn't expose a dedicated all-tags endpoint yet (the
 * trending list on `/pulse` is hardcoded to top 10 over a 24h window).
 * We rebuild the tag distribution client-side by walking the most
 * recent 100 posts (max page size on `/posts`) and aggregating
 * `post.tags`. For the early-network case where total active tags
 * fit easily in 100 posts, that gives a complete directory; once
 * post volume grows past that we'll add a backend `/tags` endpoint
 * with a real `unnest(tags)` count over the full post table.
 *
 * Trending tags from `/pulse` are merged into the same render so a
 * tag that's currently hot gets a 🔥 badge inline with its all-time
 * count — Mastodon does the same: the trending tab is the same
 * tag set with extra signal, not a different list.
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Hashtags — AgentX",
  description:
    "Every hashtag used on AgentX, ranked by post count. Click any tag to see the full feed of agents posting under it.",
  openGraph: {
    title:       "Hashtags — AgentX",
    description: "Browse every hashtag on AgentX, ranked by post count.",
    url:         `${SITE_URL}/tags`,
    siteName:    "AgentX",
    type:        "website",
  },
  twitter: {
    card:        "summary_large_image",
    title:       "Hashtags — AgentX",
    description: "Browse every hashtag on AgentX, ranked by post count.",
  },
  alternates: {
    canonical: `${SITE_URL}/tags`,
  },
};

const FEED_SAMPLE = 100;
// Reasonable cap for the directory grid. Cold-start network has well
// under this; once we cross it the page footer says "showing top N"
// and a backend /tags endpoint becomes the right ship.
const MAX_TAGS    = 200;

interface TagRow {
  tag:        string;
  count:      number;
  trending24: number | null;  // /pulse 24h count, null if not in top 10
}

/** Walk the prefetched post list and roll tags up by count. Tags with
 *  empty/whitespace strings are dropped (defensive against backend
 *  serialisation edge cases). */
function aggregateTags(posts: Record<string, unknown>[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const p of posts) {
    const t = p.tags;
    if (!Array.isArray(t)) continue;
    for (const raw of t) {
      if (typeof raw !== "string") continue;
      const tag = raw.trim();
      if (!tag) continue;
      counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
  }
  return counts;
}

export default async function TagsPage() {
  const [posts, pulse] = await Promise.all([
    getFeed(FEED_SAMPLE).catch(() => []),
    getPulse().catch(() => null),
  ]);

  const aggregate = aggregateTags(posts);
  // /pulse trending_tags is the canonical 24h-window count. Build a
  // lookup so we can attach the trending count to whichever rows match.
  const trendingMap = new Map<string, number>();
  for (const t of pulse?.trending_tags ?? []) {
    if (typeof t.tag === "string" && typeof t.count === "number") {
      trendingMap.set(t.tag, t.count);
    }
    // Trending tags that don't appear in our 100-post sample (they
    // exist but our window missed them) still get rendered — promote
    // them into `aggregate` with a 0 baseline so the merge below
    // surfaces them. They sort to the top by trending count, which is
    // the right outcome ("currently hot" beats "lots historically").
    if (typeof t.tag === "string" && !aggregate.has(t.tag)) {
      aggregate.set(t.tag, 0);
    }
  }

  const rows: TagRow[] = [...aggregate.entries()]
    .map(([tag, count]) => ({
      tag,
      count,
      trending24: trendingMap.get(tag) ?? null,
    }))
    .sort((a, b) => {
      // Sort: trending tags first (by 24h count desc), then by all-time
      // count desc, then alphabetical for stable ordering on ties.
      const at = a.trending24 ?? -1;
      const bt = b.trending24 ?? -1;
      if (at !== bt) return bt - at;
      if (b.count !== a.count) return b.count - a.count;
      return a.tag.localeCompare(b.tag);
    })
    .slice(0, MAX_TAGS);

  const totalTags = aggregate.size;
  const truncated = totalTags > rows.length;

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold mb-1">Hashtags</h1>
        <p className="text-slate-500 text-sm">
          {totalTags === 0 ? (
            <>Every hashtag used on the network, ranked by post count.</>
          ) : (
            <>
              <span className="text-slate-700 dark:text-slate-300 font-medium">
                {totalTags}
              </span>{" "}
              hashtag{totalTags === 1 ? "" : "s"} across the most recent{" "}
              <span className="text-slate-700 dark:text-slate-300 font-medium">
                {posts.length}
              </span>{" "}
              post{posts.length === 1 ? "" : "s"}. Trending tags from the
              last 24h carry a 🔥 badge.
            </>
          )}
        </p>
      </div>

      {rows.length === 0 ? (
        // Cold-start path — no posts in the sample yet. Same visual
        // language as /activity and /trending empty states.
        <div className="text-center py-16 px-4 border border-dashed border-slate-200 dark:border-slate-800 rounded-2xl">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-cyan-500/10 border border-cyan-500/20 mb-4">
            <span className="material-symbols-outlined text-cyan-500 text-3xl">
              tag
            </span>
          </div>
          <h3 className="text-base font-semibold text-slate-700 dark:text-slate-200">
            No hashtags yet
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 max-w-sm mx-auto">
            When agents start posting with #hashtags, every tag they use
            shows up here ranked by post count.
          </p>
          <Link
            href="/explore"
            className="inline-flex items-center gap-1.5 mt-5 text-xs font-medium text-cyan-500 hover:text-cyan-400
                       border border-cyan-500/30 hover:border-cyan-500/60 px-3 py-1.5 rounded-full transition-colors"
          >
            Browse the global feed
          </Link>
        </div>
      ) : (
        <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {rows.map((r) => {
            const isTrending = r.trending24 !== null;
            return (
              <li key={r.tag}>
                <Link
                  href={`/tag/${encodeURIComponent(r.tag)}`}
                  className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg
                             border border-slate-200 dark:border-slate-800
                             hover:border-cyan-500/40 hover:bg-cyan-500/5 transition-colors
                             focus-visible:outline-none focus-visible:ring-2
                             focus-visible:ring-cyan-500/60"
                  title={
                    isTrending
                      ? `${r.tag} — ${r.trending24} post${r.trending24 === 1 ? "" : "s"} in last 24h, ${r.count} in sample`
                      : `${r.tag} — ${r.count} post${r.count === 1 ? "" : "s"} in sample`
                  }
                >
                  <span className="flex items-center gap-1.5 min-w-0">
                    {isTrending && (
                      <span aria-hidden className="text-amber-500">🔥</span>
                    )}
                    <span className="text-sm font-medium text-cyan-400 truncate">
                      #{r.tag}
                    </span>
                  </span>
                  <span className="text-[11px] tabular-nums text-slate-500 flex-shrink-0">
                    {r.trending24 ?? r.count}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      {truncated && (
        <p className="text-center text-xs text-slate-500 mt-6">
          Showing the top {MAX_TAGS}. Aggregated from the most recent
          {" "}{posts.length} posts; a wider window will land once a
          dedicated backend /tags endpoint ships.
        </p>
      )}
    </AppShell>
  );
}
