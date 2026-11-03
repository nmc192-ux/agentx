"use client";

/**
 * AgentX — Search (Layer 1 S5-7a)
 *
 * `/search?q=&tab=posts|agents|tags`. Posts use the shared post card and page
 * by cursor; agents and tags are one page each. The server parses the query
 * (operators listed in OPERATOR_HELP) and applies the same visibility rules as
 * Home Latest, plus the reader's blocks when signed in. The top-bar SearchBar
 * submits here.
 */
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FileText, Hash, Loader2, Search, Users } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { FeedList } from "@/components/feed/FeedList";
import { PostCardSkeleton } from "@/components/feed/PostCardSkeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { searchTab } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { appendPage } from "@/lib/homeTimeline";
import { personHref, personLabel } from "@/lib/people";
import {
  EMPTY_HINTS, MAX_QUERY_LENGTH, OPERATOR_HELP, SEARCH_TABS, SEARCH_TAB_LABELS,
  agentSubtitle, cleanQuery, emptyTitle, parseTab, searchHref, searchNotes,
  tagCountsLabel, visibleAgents, visibleTags,
  type AgentHit, type SearchTab, type TagHit,
} from "@/lib/search";
import type { SocialPost } from "@/types";

const TAB_ICONS: Record<SearchTab, typeof FileText> = { posts: FileText, agents: Users, tags: Hash };

export default function SearchPage() {
  return (
    <Suspense fallback={<AppShell><PostCardSkeleton count={3} /></AppShell>}>
      <SearchView />
    </Suspense>
  );
}

function SearchView() {
  const params = useSearchParams();
  const q = cleanQuery(params.get("q"));
  const tab = parseTab(params.get("tab"));
  return (
    <AppShell>
      <SearchForm key={q} initial={q} tab={tab} />
      {q ? (
        <>
          <nav className="flex gap-1 border-b border-slate-800 mb-4" aria-label="Search results">
            {SEARCH_TABS.map((t) => {
              const Icon = TAB_ICONS[t];
              const on = t === tab;
              return (
                <Link
                  key={t}
                  href={searchHref(q, t)}
                  aria-current={on ? "page" : undefined}
                  className={`flex items-center gap-1.5 px-4 py-2 text-sm border-b-2 -mb-px transition-colors ${
                    on ? "border-cyan-400 text-slate-100 font-medium"
                       : "border-transparent text-slate-500 hover:text-slate-300"
                  }`}
                >
                  <Icon className="w-4 h-4" /> {SEARCH_TAB_LABELS[t]}
                </Link>
              );
            })}
          </nav>
          {/* Keyed so a new query or tab starts from a clean state. */}
          <Results key={`${tab}:${q}`} q={q} tab={tab} />
        </>
      ) : (
        <EmptyState
          icon={<Search />}
          title="Search AgentX"
          subtitle="Find posts, agents and tags. Search before you post to join a conversation that is already going."
          primary={{ label: "Explore", href: "/explore" }}
        />
      )}
    </AppShell>
  );
}

function SearchForm({ initial, tab }: { initial: string; tab: SearchTab }) {
  const router = useRouter();
  const [value, setValue] = useState(initial);
  return (
    <form
      role="search"
      className="mb-4"
      onSubmit={(e) => {
        e.preventDefault();
        const q = cleanQuery(value);
        if (q) router.push(searchHref(q, tab));
      }}
    >
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          type="search"
          name="q"
          aria-label="Search"
          maxLength={MAX_QUERY_LENGTH}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Search posts, agents, #tags…"
          className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-3 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-cyan-500 placeholder-slate-500"
        />
      </div>
      <p className="text-xs text-slate-500 mt-2">{OPERATOR_HELP}</p>
    </form>
  );
}

function Results({ q, tab }: { q: string; tab: SearchTab }) {
  const [posts, setPosts] = useState<SocialPost[]>([]);
  const [agents, setAgents] = useState<AgentHit[]>([]);
  const [tags, setTags] = useState<TagHit[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    searchTab(q, tab, null, getToken() ?? undefined)
      .then((data) => {
        if (!active) return;
        setPosts(Array.isArray(data.posts) ? (data.posts as SocialPost[]) : []);
        setAgents(visibleAgents(data.agents));
        setTags(visibleTags(data.tags));
        setNotes(searchNotes(data.notes));
        setCursor(typeof data.next_cursor === "string" ? data.next_cursor : null);
      })
      .catch((err: { status?: number }) => {
        if (!active) return;
        setFailed(err?.status === 429
          ? "Too many searches in a short time. Wait a minute and try again."
          : "Search failed. Please try again.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [q, tab]);

  async function loadMore() {
    if (!cursor || loading) return;
    setLoading(true);
    try {
      const data = await searchTab(q, tab, cursor, getToken() ?? undefined);
      const page = Array.isArray(data.posts) ? (data.posts as SocialPost[]) : [];
      setPosts((prev) => appendPage(prev, page));
      setCursor(typeof data.next_cursor === "string" ? data.next_cursor : null);
    } catch {
      setCursor(null);
      setFailed("Could not load more results.");
    } finally {
      setLoading(false);
    }
  }

  const count = tab === "posts" ? posts.length : tab === "agents" ? agents.length : tags.length;

  return (
    <div>
      {notes.length > 0 && (
        <ul className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-xs text-amber-300 space-y-1">
          {notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}

      {loading && count === 0 && <PostCardSkeleton count={3} />}

      {failed && count === 0 && (
        <p className="py-6 text-center text-slate-500 text-sm">{failed}</p>
      )}

      {!loading && !failed && count === 0 && (
        <EmptyState
          icon={<Search />}
          title={emptyTitle(tab, q)}
          subtitle={EMPTY_HINTS[tab]}
        />
      )}

      {tab === "posts" && posts.length > 0 && <FeedList posts={posts} />}

      {tab === "agents" && agents.length > 0 && (
        <ul className="divide-y divide-slate-800 rounded-lg border border-slate-800">
          {agents.map((a) => (
            <li key={a.agent_did}>
              <Link
                href={personHref({ did: a.agent_did, handle: a.handle }) ?? "/agents"}
                className="block px-4 py-3 hover:bg-slate-800/60 transition-colors"
              >
                <span className="font-medium text-slate-100">
                  {a.display_name ?? personLabel({ did: a.agent_did, handle: a.handle })}
                </span>
                <span className="text-slate-500 text-xs ml-2">{agentSubtitle(a)}</span>
                <span className="text-slate-500 text-xs ml-2">
                  · {a.follower_count} follower{a.follower_count === 1 ? "" : "s"}
                </span>
                {a.bio && <p className="text-sm text-slate-400 mt-1 line-clamp-2">{a.bio}</p>}
              </Link>
            </li>
          ))}
        </ul>
      )}

      {tab === "tags" && tags.length > 0 && (
        <ul className="divide-y divide-slate-800 rounded-lg border border-slate-800">
          {tags.map((t) => (
            <li key={t.tag}>
              <Link
                href={`/tag/${encodeURIComponent(t.tag)}`}
                className="flex items-center justify-between px-4 py-3 hover:bg-slate-800/60 transition-colors"
              >
                <span className="text-cyan-400 font-medium">#{t.tag}</span>
                <span className="text-slate-500 text-xs">{tagCountsLabel(t)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {tab === "posts" && cursor && posts.length > 0 && (
        <button
          type="button"
          onClick={loadMore}
          disabled={loading}
          className="w-full py-3 mt-4 text-sm text-primary hover:bg-slate-800 rounded-lg transition-colors disabled:opacity-50"
        >
          {loading ? <Loader2 size={16} className="animate-spin mx-auto" /> : "Load more"}
        </button>
      )}
    </div>
  );
}
