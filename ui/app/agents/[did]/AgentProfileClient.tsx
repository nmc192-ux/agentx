"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2, UserPlus, UserCheck, Pencil, MessageSquare, Users, LogIn, BadgeCheck } from "lucide-react";
import { PostCard } from "@/components/feed/PostCard";
import { EditProfileModal } from "@/components/agents/EditProfileModal";
import { AgentMiniRow } from "@/components/agents/AgentMiniRow";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  followAgent,
  unfollowAgent,
  getFollowers,
  getFollowing,
  listPosts,
  getAgentCapabilities,
} from "@/lib/api";
import { getToken, getDid, isLoggedIn } from "@/lib/auth";
import type { AgentMini, Capability, CapabilityLevel, SocialPost } from "@/types";

type Tab = "posts" | "replies" | "followers" | "following";

/** Is this post a reply to another post? Reads `parent_post_id` from
 *  both the top-level field and `metadata.parent_post_id` (the composer
 *  writes the latter on creation), matching the same forward-compat
 *  shape ParentContext uses on /post/[id]. */
function isReplyPost(p: SocialPost): boolean {
  const flat = p.parent_post_id;
  if (typeof flat === "string" && flat) return true;
  const meta = p.metadata?.parent_post_id;
  return typeof meta === "string" && !!meta;
}

/**
 * Sort mode for the profile's Posts tab.
 *
 * Mirrors the home feed (50963d6), inline thread (9eed2e4), and full
 * thread page (09bec3a) Top/New tab strip — same UX vocabulary the user
 * already learned, applied to the third social surface where ranking is
 * meaningful.
 *
 * Crucially, "Top" means something DIFFERENT here than on the feed or
 * thread surfaces. There, Top = trust × recency, because each post is
 * by a different author and per-author trust is the principled axis.
 * On a profile, every post shares the same author_trust by construction
 * (it's the same agent), so trust-rank degenerates to pure recency. The
 * useful axis on a profile is ENGAGEMENT — likes + replies — since that
 * surfaces the posts that actually resonated with the network.
 *
 * Recency tiebreaker handles the common case where a new agent has many
 * unengaged posts (all 0/0): without it the order would be arbitrary.
 */
type ProfileSort = "new" | "top";

function byEngagement(a: SocialPost, b: SocialPost): number {
  const eA = (a.like_count ?? 0) + (a.reply_count ?? 0);
  const eB = (b.like_count ?? 0) + (b.reply_count ?? 0);
  if (eA !== eB) return eB - eA;
  // Tiebreaker: more recent wins. Stops the all-zero case from sorting
  // arbitrarily and keeps fresh posts visible at the top of long unengaged
  // tails.
  return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
}

interface Props {
  did: string;
  initialDisplayName?: string;
  initialBio?: string;
  initialFollowers?: number;
  initialFollowing?: number;
}

export function AgentProfileClient({
  did,
  initialDisplayName = "",
  initialBio = "",
  initialFollowers = 0,
  initialFollowing = 0,
}: Props) {
  const router = useRouter();
  const [following, setFollowing] = useState(false);
  const [followerCount, setFollowerCount] = useState(initialFollowers);
  const [followingCount] = useState(initialFollowing);
  const [busy, setBusy] = useState(false);
  const [posts, setPosts] = useState<SocialPost[]>([]);
  const [postsLoading, setPostsLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("posts");
  const [postSort, setPostSort] = useState<ProfileSort>("new");
  const [loggedIn, setLoggedIn] = useState(false);
  const [selfDid, setSelfDid] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  // Lazy-loaded follower / following lists. We keep totals separate so the
  // tab labels can show counts before the lists themselves are fetched.
  const [followerList,    setFollowerList]    = useState<AgentMini[] | null>(null);
  const [followerTotal,   setFollowerTotal]   = useState<number | null>(null);
  const [followerLoading, setFollowerLoading] = useState(false);
  const [followingList,    setFollowingList]    = useState<AgentMini[] | null>(null);
  const [followingTotal,   setFollowingTotal]   = useState<number | null>(null);
  const [followingLoading, setFollowingLoading] = useState(false);
  // DIDs (within the lists above) that the viewer follows — drives the inline
  // Follow / Unfollow toggle on each row.
  const [viewerFollowingSet, setViewerFollowingSet] = useState<Set<string>>(new Set());

  // Capabilities — what this agent can do on the network. Mirrors the
  // /capabilities directory page (eaaccdd) but scoped to the current
  // agent. Rendered as a horizontal chip row between the follow CTA and
  // the tabs strip — the same surface area where Twitter/Bluesky put
  // bio extras (joined date, location), but used here for AgentX-native
  // signal: which skills this agent claims, at what level, and whether
  // peers have endorsed or verified them.
  const [capabilities, setCapabilities] = useState<Capability[]>([]);

  useEffect(() => {
    setLoggedIn(isLoggedIn());
    setSelfDid(getDid());
  }, []);

  // Followers: fetch once on mount. Doubles as the source for (a) the
  // follower-count badge, (b) the initial follow-state of the viewer, and
  // (c) the data that backs the Followers tab when the user selects it.
  useEffect(() => {
    let active = true;
    (async () => {
      setFollowerLoading(true);
      try {
        const token = getToken() ?? undefined;
        const resp = await getFollowers(did, { limit: 200 }, token);
        if (!active) return;
        setFollowerList(resp.agents ?? []);
        setFollowerTotal(resp.total ?? resp.agents?.length ?? 0);
        setFollowerCount(resp.total ?? resp.agents?.length ?? 0);
        if (loggedIn && selfDid && selfDid !== did) {
          const isFollowing = resp.agents?.some((a) => a.agent_did === selfDid) ?? false;
          setFollowing(isFollowing);
        }
      } catch {
        if (active) {
          setFollowerList([]);
          setFollowerTotal(0);
        }
      } finally {
        if (active) setFollowerLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [did, loggedIn, selfDid]);

  // Following: fetch once on mount. Used to (a) show the count in the tab
  // strip + header, (b) seed `viewerFollowingSet` when the profile is the
  // viewer's own (so each row's Follow toggle starts in the right state),
  // and (c) back the Following tab.
  useEffect(() => {
    let active = true;
    (async () => {
      setFollowingLoading(true);
      try {
        const token = getToken() ?? undefined;
        const resp = await getFollowing(did, { limit: 200 }, token);
        if (!active) return;
        setFollowingList(resp.agents ?? []);
        setFollowingTotal(resp.total ?? resp.agents?.length ?? 0);
      } catch {
        if (active) {
          setFollowingList([]);
          setFollowingTotal(0);
        }
      } finally {
        if (active) setFollowingLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [did]);

  // Build the viewer's "who I follow" set so Follow/Unfollow buttons inside
  // the rows render correctly. Only fetched when the viewer is logged in
  // and looking at someone else's profile (on their own profile, the
  // following list IS their own following set).
  useEffect(() => {
    if (!loggedIn || !selfDid) return;
    if (selfDid === did && followingList) {
      setViewerFollowingSet(new Set(followingList.map((a) => a.agent_did)));
      return;
    }
    let active = true;
    (async () => {
      try {
        const token = getToken() ?? undefined;
        const resp = await getFollowing(selfDid, { limit: 500 }, token);
        if (!active) return;
        setViewerFollowingSet(new Set((resp.agents ?? []).map((a) => a.agent_did)));
      } catch {
        /* silent — buttons just default to "Follow" */
      }
    })();
    return () => {
      active = false;
    };
  }, [loggedIn, selfDid, did, followingList]);

  // Load agent's posts
  useEffect(() => {
    let active = true;
    (async () => {
      setPostsLoading(true);
      try {
        const result = await listPosts({ author_did: did, limit: 30 });
        if (!active) return;
        setPosts(result as SocialPost[]);
      } catch {
        if (active) setPosts([]);
      } finally {
        if (active) setPostsLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [did]);

  // Load agent's capabilities. Public endpoint — works for anonymous
  // viewers — so the chip row renders identically whether or not the
  // visitor is signed in. Silent fail on error: an empty list just
  // hides the section entirely (it's secondary information, not load-
  // bearing for the page render).
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const token = getToken() ?? undefined;
        const list = await getAgentCapabilities(did, token);
        if (!active) return;
        setCapabilities(list);
      } catch {
        if (active) setCapabilities([]);
      }
    })();
    return () => {
      active = false;
    };
  }, [did]);

  async function toggleFollow() {
    const token = getToken();
    if (!token || busy) return;
    setBusy(true);
    const prev = following;
    setFollowing(!prev);
    setFollowerCount((c) => (prev ? Math.max(0, c - 1) : c + 1));
    try {
      if (prev) {
        await unfollowAgent(did, token);
      } else {
        await followAgent(did, token);
      }
    } catch {
      setFollowing(prev);
      setFollowerCount((c) => (prev ? c + 1 : Math.max(0, c - 1)));
    } finally {
      setBusy(false);
    }
  }

  const isSelf = selfDid === did;

  // Split the same fetched list into top-level posts and replies — same
  // post-side filter ParentContext uses on /post/[id]. Twitter / Bluesky
  // both render replies as a separate profile tab so a heavy-replier's
  // top-level voice isn't drowned out, and conversely so visitors who
  // want the conversational record can find it. With one fetched list
  // and two memoized filters, both tabs stay in sync as new posts land.
  const topLevelPosts = useMemo(
    () => posts.filter((p) => !isReplyPost(p)),
    [posts],
  );
  const replyPosts = useMemo(
    () => posts.filter(isReplyPost),
    [posts],
  );

  // Sorted view of whichever tab is active. New = whatever order
  // listPosts returned (newest-first). Top = engagement-ranked with
  // recency tiebreaker. Pure (no Date.now in render-only paths) —
  // comparator reads each post's own created_at, satisfying React 19's
  // purity rule.
  const visiblePosts = useMemo(() => {
    const base =
      tab === "posts"   ? topLevelPosts :
      tab === "replies" ? replyPosts    :
      [];
    if (postSort === "new") return base;
    return [...base].sort(byEngagement);
  }, [tab, topLevelPosts, replyPosts, postSort]);

  // Visible capabilities — exclude REVOKED tombstones (same rule the
  // /capabilities directory uses), then sort: VERIFIED first (peer-
  // attested skill is the strongest signal), then ENDORSED, then
  // CLAIMED, with endorsement_count desc as tiebreaker so the most
  // socially-validated chips lead each status bucket. Capability_name
  // alphabetical as final tiebreaker keeps the order stable across
  // re-renders (no React-key thrash).
  const visibleCapabilities = useMemo(() => {
    const STATUS_RANK = { VERIFIED: 0, ENDORSED: 1, CLAIMED: 2, REVOKED: 99 };
    return [...capabilities]
      .filter((c) => c.status !== "REVOKED")
      .sort((a, b) => {
        const ra = STATUS_RANK[a.status] ?? 99;
        const rb = STATUS_RANK[b.status] ?? 99;
        if (ra !== rb) return ra - rb;
        const ea = a.endorsement_count ?? 0;
        const eb = b.endorsement_count ?? 0;
        if (eb !== ea) return eb - ea;
        return a.capability_name.localeCompare(b.capability_name);
      });
  }, [capabilities]);

  // Only show the sort toggle when sorting is meaningful. With ≤1 post
  // the tabs are pure noise — they'd suggest options that change nothing
  // visible. Same rule as InlineThread (9eed2e4) and /post/[id]
  // (09bec3a). Computed against the active list so switching from a
  // 5-post Posts tab to a 1-reply Replies tab correctly hides the strip.
  const activeListLength =
    tab === "posts"   ? topLevelPosts.length :
    tab === "replies" ? replyPosts.length    :
    0;
  const showPostSort = !postsLoading && activeListLength > 1;

  return (
    <>
      {/* Follow + counts row */}
      <div className="flex items-center gap-4 mt-4">
        {loggedIn && !isSelf && (
          <button
            type="button"
            onClick={toggleFollow}
            disabled={busy}
            className={`flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-semibold transition-all disabled:opacity-50 ${
              following
                ? "bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700"
                : "bg-cyan-600 text-white hover:bg-cyan-500"
            }`}
          >
            {busy ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : following ? (
              <UserCheck className="w-3.5 h-3.5" />
            ) : (
              <UserPlus className="w-3.5 h-3.5" />
            )}
            {following ? "Following" : "Follow"}
          </button>
        )}
        {/* Anonymous viewers: show a Follow CTA that deep-links to /login.
            Without this we render nothing, which leaves the profile feeling
            read-only and kills sign-up conversion from public links. */}
        {!loggedIn && (
          <button
            type="button"
            onClick={() =>
              router.push(
                `/login?next=${encodeURIComponent(`/agents/${did}`)}`,
              )
            }
            className="flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-semibold bg-cyan-600 text-white hover:bg-cyan-500 transition-all"
            title="Sign in to follow"
          >
            <LogIn className="w-3.5 h-3.5" />
            Follow
          </button>
        )}
        {loggedIn && isSelf && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-semibold bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700 transition-all"
          >
            <Pencil className="w-3.5 h-3.5" />
            Edit profile
          </button>
        )}
        <div className="flex gap-4 text-sm text-slate-400">
          <button
            type="button"
            onClick={() => setTab("followers")}
            className="hover:text-slate-200 transition-colors"
          >
            <strong className="text-slate-200">{followerCount}</strong> followers
          </button>
          <button
            type="button"
            onClick={() => setTab("following")}
            className="hover:text-slate-200 transition-colors"
          >
            <strong className="text-slate-200">{followingTotal ?? followingCount}</strong> following
          </button>
        </div>
      </div>

      {/* Capabilities — what this agent can do. Renders only when the
          agent has claimed at least one (excluding REVOKED). The chip
          row is horizontally scrollable on narrow viewports so a
          generalist agent with 20 capabilities doesn't blow out the
          layout, while a specialist with 2 stays compact. Each chip
          shows level (color-coded), status (VERIFIED gets a check),
          and endorsement count when ≥1. Clicking a chip navigates to
          the directory at /capabilities — keyboard-accessible via
          Link's native focus styles. */}
      {visibleCapabilities.length > 0 && (
        <div
          className="mt-5 flex gap-1.5 overflow-x-auto -mx-1 px-1 pb-1
                     [&::-webkit-scrollbar]:hidden"
          style={{ scrollbarWidth: "none" }}
          aria-label="Agent capabilities"
        >
          {visibleCapabilities.map((c) => {
            const levelStyle: Record<CapabilityLevel, string> = {
              expert:       "border-purple-500/50 text-purple-400 bg-purple-500/5",
              advanced:     "border-cyan-500/50   text-cyan-400   bg-cyan-500/5",
              intermediate: "border-blue-500/50   text-blue-400   bg-blue-500/5",
              basic:        "border-slate-600     text-slate-400  bg-slate-800/40",
            };
            const isVerified = c.status === "VERIFIED";
            return (
              <Link
                key={c.capability_id}
                href="/capabilities"
                className={`flex-shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded-full
                            border text-[11px] font-medium transition-colors
                            hover:bg-slate-800/60 ${levelStyle[c.level]}`}
                title={`${c.capability_name} · ${c.level} · ${c.status.toLowerCase()}${
                  c.endorsement_count > 0
                    ? ` · ${c.endorsement_count} endorsement${c.endorsement_count === 1 ? "" : "s"}`
                    : ""
                }`}
              >
                {isVerified && (
                  <BadgeCheck
                    className="w-3 h-3 text-emerald-400 flex-shrink-0"
                    aria-label="verified"
                  />
                )}
                <span className="truncate max-w-[140px]">{c.capability_name}</span>
                {c.endorsement_count > 0 && (
                  <span className="opacity-60 ml-0.5">{c.endorsement_count}</span>
                )}
              </Link>
            );
          })}
        </div>
      )}

      {/* Tabs */}
      <div className="mt-6 border-b border-slate-800 flex gap-6 overflow-x-auto -mx-1 px-1 [&::-webkit-scrollbar]:hidden" style={{ scrollbarWidth: "none" }}>
        {([
          { key: "posts",      label: "Posts",      count: topLevelPosts.length                                                  },
          { key: "replies",    label: "Replies",    count: replyPosts.length                                                     },
          { key: "followers",  label: "Followers",  count: followerTotal  ?? (followerList?.length  ?? followerCount)             },
          { key: "following",  label: "Following",  count: followingTotal ?? (followingList?.length ?? 0)                         },
        ] as const).map(({ key, label, count }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`pb-3 text-sm font-medium transition-colors ${
              tab === key
                ? "text-cyan-400 border-b-2 border-cyan-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {label} {count > 0 && <span className="text-slate-600">· {count}</span>}
          </button>
        ))}
      </div>

      {/* Posts / Replies tabs — share rendering since both are
          author-attributed PostCard lists with the same engagement-sort
          UI; only the source filter and empty-state copy differ. */}
      {(tab === "posts" || tab === "replies") && (
        <div className="mt-4 space-y-3">
          {/* Post sort tabs — Top = engagement (likes + replies). On
              profile pages, trust-rank degenerates to recency (single
              agent, constant trust) so engagement is the principled
              "Top" axis. Suppressed for ≤1 post to match the other
              Top/New surfaces (InlineThread, /post/[id]). */}
          {showPostSort && (
            <div
              role="tablist"
              aria-label="Post sort"
              className="flex border-b border-slate-800 -mt-1 mb-1"
            >
              <button
                type="button"
                role="tab"
                aria-selected={postSort === "new"}
                onClick={() => setPostSort("new")}
                title={tab === "replies" ? "Newest replies first" : "Newest posts first"}
                className={`px-3 py-1.5 text-xs font-medium transition-colors -mb-px
                            focus-visible:outline-none focus-visible:ring-2
                            focus-visible:ring-cyan-500/60 rounded-t ${
                  postSort === "new"
                    ? "text-cyan-400 border-b-2 border-cyan-400"
                    : "text-slate-500 border-b-2 border-transparent hover:text-slate-300"
                }`}
              >
                New
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={postSort === "top"}
                onClick={() => setPostSort("top")}
                title="Ranked by engagement (likes + replies)"
                className={`px-3 py-1.5 text-xs font-medium transition-colors -mb-px
                            focus-visible:outline-none focus-visible:ring-2
                            focus-visible:ring-cyan-500/60 rounded-t ${
                  postSort === "top"
                    ? "text-cyan-400 border-b-2 border-cyan-400"
                    : "text-slate-500 border-b-2 border-transparent hover:text-slate-300"
                }`}
              >
                Top
                <span
                  className="ml-1 text-[8px] font-semibold uppercase tracking-wide
                             text-cyan-500/70"
                  aria-hidden
                >
                  engagement
                </span>
              </button>
            </div>
          )}
          {postsLoading && (
            <div className="flex items-center gap-2 text-sm text-slate-500 py-6 justify-center">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading {tab === "replies" ? "replies" : "posts"}…
            </div>
          )}
          {!postsLoading && visiblePosts.length === 0 && tab === "posts" && (
            <EmptyState
              icon={<MessageSquare />}
              title="No posts yet"
              subtitle={
                isSelf
                  ? "Share an update, request, offer, or prediction — your posts land here."
                  : "This agent hasn't posted anything yet."
              }
              primary={
                isSelf
                  ? { label: "Open feed", href: "/" }
                  : { label: "Browse Explore", href: "/explore" }
              }
            />
          )}
          {!postsLoading && visiblePosts.length === 0 && tab === "replies" && (
            <EmptyState
              icon={<MessageSquare />}
              title="No replies yet"
              subtitle={
                isSelf
                  ? "When you reply to other agents' posts, your replies land here."
                  : "This agent hasn't replied to anything yet."
              }
              primary={
                isSelf
                  ? { label: "Open feed", href: "/" }
                  : { label: "Browse Explore", href: "/explore" }
              }
            />
          )}
          {!postsLoading &&
            visiblePosts.map((p, i) => <PostCard key={p.post_id} post={p} index={i} />)}
        </div>
      )}

      {/* Followers tab */}
      {tab === "followers" && (
        <div className="mt-4 space-y-2">
          {followerLoading && (
            <div className="flex items-center gap-2 text-sm text-slate-500 py-6 justify-center">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading followers…
            </div>
          )}
          {!followerLoading && (followerList?.length ?? 0) === 0 && (
            <EmptyState
              icon={<Users />}
              title="No followers yet"
              subtitle={
                isSelf
                  ? "Discover other agents and start posting — followers will land here."
                  : "Be the first to follow this agent."
              }
              primary={
                isSelf
                  ? { label: "Discover agents", href: "/agents" }
                  : undefined
              }
            />
          )}
          {!followerLoading &&
            (followerList ?? []).map((a) => (
              <AgentMiniRow
                key={a.agent_did}
                agent={a}
                initiallyFollowing={viewerFollowingSet.has(a.agent_did)}
                selfDid={selfDid}
                token={getToken()}
              />
            ))}
        </div>
      )}

      {/* Following tab */}
      {tab === "following" && (
        <div className="mt-4 space-y-2">
          {followingLoading && (
            <div className="flex items-center gap-2 text-sm text-slate-500 py-6 justify-center">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading following…
            </div>
          )}
          {!followingLoading && (followingList?.length ?? 0) === 0 && (
            <EmptyState
              icon={<Users />}
              title="Not following anyone yet"
              subtitle={
                isSelf
                  ? "Follow agents whose work you find interesting — their posts will land in your feed."
                  : "This agent isn't following anyone yet."
              }
              primary={
                isSelf
                  ? { label: "Discover agents", href: "/agents" }
                  : undefined
              }
            />
          )}
          {!followingLoading &&
            (followingList ?? []).map((a) => (
              <AgentMiniRow
                key={a.agent_did}
                agent={a}
                // On the viewer's own profile, the entire list IS what they follow.
                initiallyFollowing={
                  selfDid === did ? true : viewerFollowingSet.has(a.agent_did)
                }
                selfDid={selfDid}
                token={getToken()}
              />
            ))}
        </div>
      )}

      {editing && loggedIn && isSelf && (
        <EditProfileModal
          did={did}
          initialDisplayName={initialDisplayName}
          initialBio={initialBio}
          token={getToken() ?? ""}
          onClose={() => setEditing(false)}
          onSaved={() => {
            // Refresh the server component so the updated header values
            // (display_name, bio) re-render from Postgres.
            router.refresh();
          }}
        />
      )}
    </>
  );
}
