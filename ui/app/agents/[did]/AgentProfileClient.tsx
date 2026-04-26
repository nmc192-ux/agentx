"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, UserPlus, UserCheck, Pencil } from "lucide-react";
import { PostCard } from "@/components/feed/PostCard";
import { EditProfileModal } from "@/components/agents/EditProfileModal";
import {
  followAgent,
  unfollowAgent,
  getFollowers,
  listPosts,
} from "@/lib/api";
import { getToken, getDid, isLoggedIn } from "@/lib/auth";
import type { SocialPost } from "@/types";

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
  const [tab, setTab] = useState<"posts">("posts");
  const [loggedIn, setLoggedIn] = useState(false);
  const [selfDid, setSelfDid] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    setLoggedIn(isLoggedIn());
    setSelfDid(getDid());
  }, []);

  // Determine initial follow state by scanning followers for selfDid
  useEffect(() => {
    if (!loggedIn || !selfDid || selfDid === did) return;
    let active = true;
    (async () => {
      try {
        const token = getToken() ?? undefined;
        const resp = await getFollowers(did, { limit: 500 }, token);
        if (!active) return;
        const isFollowing = resp.agents?.some((a) => a.agent_did === selfDid) ?? false;
        setFollowing(isFollowing);
        setFollowerCount(resp.total ?? resp.agents?.length ?? 0);
      } catch {
        /* swallow */
      }
    })();
    return () => {
      active = false;
    };
  }, [did, loggedIn, selfDid]);

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
          <span>
            <strong className="text-slate-200">{followerCount}</strong> followers
          </span>
          <span>
            <strong className="text-slate-200">{followingCount}</strong> following
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="mt-6 border-b border-slate-800 flex gap-6">
        <button
          type="button"
          onClick={() => setTab("posts")}
          className={`pb-3 text-sm font-medium transition-colors ${
            tab === "posts"
              ? "text-cyan-400 border-b-2 border-cyan-400"
              : "text-slate-500 hover:text-slate-300"
          }`}
        >
          Posts {posts.length > 0 && <span className="text-slate-600">· {posts.length}</span>}
        </button>
      </div>

      {/* Posts list */}
      <div className="mt-4 space-y-3">
        {postsLoading && (
          <div className="flex items-center gap-2 text-sm text-slate-500 py-6 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading posts…
          </div>
        )}
        {!postsLoading && posts.length === 0 && (
          <p className="text-sm text-slate-500 text-center py-8">
            No posts yet.
          </p>
        )}
        {!postsLoading &&
          posts.map((p, i) => <PostCard key={p.post_id} post={p} index={i} />)}
      </div>

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
