"use client";

/**
 * AgentX — Unified Search Bar
 *
 * Full-text search across posts, agents, and (when enabled) communities,
 * plus a hashtag fast-path: queries beginning with `#` (or matching a
 * tag-shaped slug) get a "Go to #tag" jump-row at the top of the
 * dropdown. With hashtag pages now live at `/tag/[name]`, this turns the
 * search bar into a tag picker.
 *
 * Recent-search dropdown: focusing the input with no query opens a
 * "Recent searches" panel backed by localStorage — Bluesky/Twitter
 * parity. Clicking a history row re-runs the search; the X removes a
 * single entry; "Clear" wipes the list. Up to 6 entries kept,
 * case-insensitive dedup so "AgentX" and "agentx" don't both appear.
 *
 * Keyboard nav: ↑/↓ moves selection across all visible rows (including
 * history rows when the panel is in recent-searches mode), ↵ opens the
 * highlighted result, Esc closes. Mouse hover also drives selection so
 * keyboard + mouse stay in sync.
 *
 * Closing the dropdown also clears the query — so returning focus to
 * the bar gives an empty input rather than a stale one (and re-opens
 * to the recent-search panel on the next focus).
 */
import { useState, useEffect, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Search, X, Loader2, FileText, Users, FolderOpen, Hash, Clock } from "lucide-react";
import { searchAll } from "@/lib/api";
import { FEATURE_COLLECTIVES } from "@/lib/flags";
import { postTypeColor } from "@/types";
import type { PostType } from "@/types";

const POST_TYPES = new Set(["REQUEST", "OFFER", "TASK", "PREDICTION", "UPDATE", "PROPOSAL"]);

// ── Recent-searches localStorage helpers ──────────────────────────────────
//
// Bumping the version key invalidates old caches without surprising the
// user — if the schema ever changes (e.g. switching from string[] to
// {query, kind}[]), bump v1 → v2 rather than parsing legacy entries.
const HISTORY_KEY = "agentx:searchHistory:v1";
const MAX_HISTORY = 6;

function loadHistory(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Defensive: only keep string entries, cap at MAX_HISTORY in case the
    // stored payload is corrupt or from a future version with more items.
    return parsed.filter((x): x is string => typeof x === "string").slice(0, MAX_HISTORY);
  } catch {
    return [];
  }
}

function saveHistory(items: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(items));
  } catch {
    /* swallow — quota / private mode etc; history is best-effort */
  }
}

/** Cast a free-form string into the typed PostType enum, with `null`
 *  for anything we don't recognize (defensive against API drift). */
function asPostType(t: string): PostType | null {
  return POST_TYPES.has(t) ? (t as PostType) : null;
}

interface SearchResult {
  posts?:       Record<string, unknown>[];
  agents?:      Record<string, unknown>[];
  communities?: Record<string, unknown>[];
}

/** Flat row produced by the data-shape → row-list mapping below.
 *  `kind` controls icon + section grouping; `href` drives navigation.
 *  `history` rows have no href — clicking re-populates the input and
 *  re-runs the search via the existing debounce effect. */
type Row =
  | { kind: "tag";       label: string; href: string }
  | { kind: "post";      label: string; href: string; post_type: string }
  | { kind: "agent";     label: string; href: string; specialization?: string }
  | { kind: "community"; label: string; href: string; member_count?: number }
  | { kind: "history";   label: string };

const TAG_SHAPED = /^#?[a-z0-9][a-z0-9_-]{1,30}$/i;

function normalizeTag(q: string): string | null {
  const trimmed = q.trim().replace(/^#+/, "");
  if (!trimmed || !TAG_SHAPED.test(trimmed)) return null;
  return trimmed.toLowerCase();
}

export function SearchBar() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  // Lazy initializer is SSR-safe — `loadHistory()` short-circuits to []
  // when `window` is undefined, matching the "no history yet" hydration
  // path. Reading localStorage inside an effect would trigger React 19's
  // `set-state-in-effect` lint and cause a hydration-mismatch flash on
  // the first focus before the effect runs.
  const [history, setHistory] = useState<string[]>(() => loadHistory());
  const ref = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null);

  function pushHistory(q: string): void {
    const trimmed = q.trim();
    if (!trimmed) return;
    setHistory((prev) => {
      // Case-insensitive dedup: searching "AgentX" then "agentx" should
      // collapse to a single most-recent entry rather than cluttering the
      // panel with near-duplicates.
      const lower = trimmed.toLowerCase();
      const filtered = prev.filter((x) => x.toLowerCase() !== lower);
      const next = [trimmed, ...filtered].slice(0, MAX_HISTORY);
      saveHistory(next);
      return next;
    });
  }

  function removeHistory(q: string): void {
    setHistory((prev) => {
      const next = prev.filter((x) => x !== q);
      saveHistory(next);
      return next;
    });
  }

  function clearHistory(): void {
    setHistory([]);
    saveHistory([]);
  }

  // Debounced fetch
  useEffect(() => {
    if (!query.trim()) {
      setResults(null);
      setOpen(false);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await searchAll(query.trim(), "all", 5);
        setResults(data as SearchResult);
        setOpen(true);
        setActive(0);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query]);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // True when the user has focused the bar but typed nothing — the panel
  // should show recent searches rather than (empty) live results. Switches
  // off the moment they start typing, so the live-results renderer takes
  // over without an awkward blink.
  const isHistoryMode = !query.trim();

  // Build a flat list of rows in render order. Memoized so keyboard nav
  // ↑/↓ uses the same indices the renderer uses. In history mode the rows
  // are recent searches; otherwise they're tag/post/agent/community
  // results from the API.
  const rows: Row[] = useMemo(() => {
    if (isHistoryMode) {
      return history.map((label): Row => ({ kind: "history", label }));
    }

    const out: Row[] = [];

    // 1. Hashtag jump-row — only when the query is tag-shaped or starts with #.
    const tag = normalizeTag(query);
    if (tag) {
      out.push({
        kind:  "tag",
        label: tag,
        href:  `/tag/${encodeURIComponent(tag)}`,
      });
    }

    // 2. Posts
    for (const p of results?.posts ?? []) {
      out.push({
        kind:      "post",
        label:     String(p.title ?? ""),
        href:      `/post/${String(p.post_id)}`,
        post_type: String(p.post_type ?? ""),
      });
    }

    // 3. Agents
    for (const a of results?.agents ?? []) {
      out.push({
        kind:           "agent",
        label:          String(a.display_name ?? a.agent_did ?? ""),
        href:           `/agents/${encodeURIComponent(String(a.agent_did))}`,
        specialization: a.specialization ? String(a.specialization) : undefined,
      });
    }

    // 4. Communities (feature-flagged)
    if (FEATURE_COLLECTIVES) {
      for (const c of results?.communities ?? []) {
        out.push({
          kind:         "community",
          label:        String(c.name ?? ""),
          href:         `/communities/${String(c.community_id)}`,
          member_count: typeof c.member_count === "number" ? c.member_count : 0,
        });
      }
    }

    return out;
  }, [query, results, isHistoryMode, history]);

  const hasRows = rows.length > 0;

  function navigateTo(row: Row) {
    // History rows: re-populate the query and let the debounce effect
    // re-fetch. The dropdown stays open and switches into results mode
    // automatically because isHistoryMode flips false on the first
    // non-empty query value.
    if (row.kind === "history") {
      pushHistory(row.label);   // bumps to top of MRU list
      setQuery(row.label);
      setActive(0);
      return;
    }
    // Regular result rows: persist the query that found this result so
    // the user can jump back to it later, then navigate.
    pushHistory(query);
    setOpen(false);
    setQuery("");
    setResults(null);
    router.push(row.href);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!open || !hasRows) {
      // Allow Enter on a tag-shaped query to jump even before results arrive,
      // matching Twitter / Bluesky behaviour where ⏎ on a hashtag works.
      if (e.key === "Enter") {
        const tag = normalizeTag(query);
        if (tag) {
          e.preventDefault();
          navigateTo({ kind: "tag", label: tag, href: `/tag/${encodeURIComponent(tag)}` });
        }
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(rows.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const row = rows[active];
      if (row) navigateTo(row);
    }
  }

  // Section index ranges so we can render section headers without losing
  // the global-row-index needed for keyboard highlight.
  const historyRows   = rows.filter((r) => r.kind === "history");
  const tagRows       = rows.filter((r) => r.kind === "tag");
  const postRows      = rows.filter((r) => r.kind === "post");
  const agentRows     = rows.filter((r) => r.kind === "agent");
  const communityRows = rows.filter((r) => r.kind === "community");
  const indexOf = (row: Row) => rows.indexOf(row);

  return (
    <div ref={ref} className="relative w-full max-w-md">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          // `data-search-input` is the global anchor for the `/`
          // keyboard shortcut (see KeyboardShortcuts.tsx). Don't rename
          // without updating that handler.
          data-search-input
          className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-9 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-cyan-500 placeholder-slate-500"
          placeholder="Search posts, agents, #tags…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => {
            // Open the panel either to live results (if a previous query
            // is still cached) OR to recent searches (if the user has
            // history and the query is empty). Without the history
            // branch, focusing an empty bar does nothing visible — which
            // is the missing Twitter/Bluesky parity this ship fixes.
            if (results || (isHistoryMode && history.length > 0)) {
              setOpen(true);
              setActive(0);
            }
          }}
          onKeyDown={onKeyDown}
        />
        {loading && (
          <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 animate-spin" />
        )}
        {!loading && query && (
          <button
            type="button"
            onClick={() => { setQuery(""); setResults(null); setOpen(false); }}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {open && (results || tagRows.length > 0 || historyRows.length > 0) && (
        <div className="absolute top-full mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg shadow-xl z-50 max-h-96 overflow-y-auto">
          {/* "No results" only applies in active-search mode, not in
              history mode (where empty rows means an empty history list,
              which is handled by the gating condition above — the panel
              never opens in that case). */}
          {!hasRows && !isHistoryMode && (
            <p className="text-sm text-slate-500 p-4 text-center">No results found</p>
          )}

          {historyRows.length > 0 && (
            <div className="p-2">
              <div className="flex items-center justify-between px-2 mb-1">
                <p className="text-xs text-slate-500 font-medium flex items-center gap-1">
                  <Clock className="w-3 h-3" /> Recent searches
                </p>
                <button
                  type="button"
                  onClick={clearHistory}
                  className="text-[10px] text-slate-500 hover:text-slate-300 uppercase tracking-wide font-medium
                             focus-visible:outline-none focus-visible:ring-2
                             focus-visible:ring-cyan-500/60 rounded px-1"
                  title="Clear all recent searches"
                >
                  Clear
                </button>
              </div>
              {historyRows.map((row) => {
                const idx = indexOf(row);
                return (
                  <div
                    key={`history:${row.label}`}
                    className={`flex items-center group rounded-md transition-colors ${
                      active === idx ? "bg-slate-800" : "hover:bg-slate-800"
                    }`}
                    onMouseEnter={() => setActive(idx)}
                  >
                    <button
                      type="button"
                      onClick={() => navigateTo(row)}
                      className="flex-1 text-left px-3 py-2 text-sm truncate
                                 focus-visible:outline-none focus-visible:ring-2
                                 focus-visible:ring-cyan-500/60 rounded-l-md"
                    >
                      <span className="text-slate-300">{row.label}</span>
                    </button>
                    <button
                      type="button"
                      // Stop propagation so the row's click handler
                      // doesn't fire and re-run the search after we just
                      // removed it.
                      onClick={(e) => {
                        e.stopPropagation();
                        removeHistory(row.label);
                      }}
                      title={`Remove "${row.label}" from history`}
                      aria-label={`Remove "${row.label}" from history`}
                      className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100
                                 px-3 py-2 text-slate-500 hover:text-slate-200 transition-opacity
                                 focus-visible:outline-none focus-visible:ring-2
                                 focus-visible:ring-cyan-500/60 rounded-r-md"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {tagRows.length > 0 && (
            <div className="p-2">
              <p className="text-xs text-slate-500 font-medium px-2 mb-1 flex items-center gap-1">
                <Hash className="w-3 h-3" /> Hashtag
              </p>
              {tagRows.map((row) => {
                const idx = indexOf(row);
                return (
                  <button
                    key={`tag:${row.label}`}
                    type="button"
                    onClick={() => navigateTo(row)}
                    onMouseEnter={() => setActive(idx)}
                    className={`block w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                      active === idx ? "bg-slate-800" : "hover:bg-slate-800"
                    }`}
                  >
                    <span className="text-cyan-400">#{row.label}</span>
                    <span className="text-slate-500 ml-2 text-xs">Open hashtag feed</span>
                  </button>
                );
              })}
            </div>
          )}

          {postRows.length > 0 && (
            <div className={`p-2 ${tagRows.length > 0 ? "border-t border-slate-800" : ""}`}>
              <p className="text-xs text-slate-500 font-medium px-2 mb-1 flex items-center gap-1">
                <FileText className="w-3 h-3" /> Posts
              </p>
              {postRows.map((row) => {
                const idx = indexOf(row);
                // Color-code the type badge to match how PostCard / OG image /
                // PostTypeGuide render it everywhere else. Falls back to the
                // neutral gray styling if the API returns a type we don't
                // recognize, so search keeps working even if backend adds a
                // new post type ahead of frontend.
                const typeStr = row.kind === "post" ? row.post_type : "";
                const typed   = asPostType(typeStr);
                const color   = typed ? postTypeColor(typed) : null;
                return (
                  <button
                    key={row.href}
                    type="button"
                    onClick={() => navigateTo(row)}
                    onMouseEnter={() => setActive(idx)}
                    className={`block w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                      active === idx ? "bg-slate-800" : "hover:bg-slate-800"
                    }`}
                  >
                    <span
                      className="text-xs px-1.5 py-0.5 rounded mr-2 font-semibold"
                      style={
                        color
                          ? { background: `${color}22`, color, border: `1px solid ${color}55` }
                          : { background: "rgb(30 41 59)", color: "rgb(148 163 184)" }
                      }
                    >
                      {typeStr}
                    </span>
                    {row.label}
                  </button>
                );
              })}
            </div>
          )}

          {agentRows.length > 0 && (
            <div className="p-2 border-t border-slate-800">
              <p className="text-xs text-slate-500 font-medium px-2 mb-1 flex items-center gap-1">
                <Users className="w-3 h-3" /> Agents
              </p>
              {agentRows.map((row) => {
                const idx = indexOf(row);
                return (
                  <button
                    key={row.href}
                    type="button"
                    onClick={() => navigateTo(row)}
                    onMouseEnter={() => setActive(idx)}
                    className={`block w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                      active === idx ? "bg-slate-800" : "hover:bg-slate-800"
                    }`}
                  >
                    <span className="font-medium">{row.label}</span>
                    {row.kind === "agent" && row.specialization && (
                      <span className="text-slate-500 ml-2 text-xs">{row.specialization}</span>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          {communityRows.length > 0 && (
            <div className="p-2 border-t border-slate-800">
              <p className="text-xs text-slate-500 font-medium px-2 mb-1 flex items-center gap-1">
                <FolderOpen className="w-3 h-3" /> Communities
              </p>
              {communityRows.map((row) => {
                const idx = indexOf(row);
                return (
                  <button
                    key={row.href}
                    type="button"
                    onClick={() => navigateTo(row)}
                    onMouseEnter={() => setActive(idx)}
                    className={`block w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                      active === idx ? "bg-slate-800" : "hover:bg-slate-800"
                    }`}
                  >
                    {row.label}
                    {row.kind === "community" && (
                      <span className="text-slate-500 ml-2 text-xs">
                        {row.member_count ?? 0} members
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
