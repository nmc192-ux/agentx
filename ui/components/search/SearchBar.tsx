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
 * Keyboard nav: ↑/↓ moves selection across all visible rows, ↵ opens the
 * highlighted result, Esc closes. Mouse hover also drives selection so
 * keyboard + mouse stay in sync.
 *
 * Closing the dropdown also clears the query — so returning focus to
 * the bar gives an empty input rather than a stale one.
 */
import { useState, useEffect, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Search, X, Loader2, FileText, Users, FolderOpen, Hash } from "lucide-react";
import { searchAll } from "@/lib/api";
import { FEATURE_COLLECTIVES } from "@/lib/flags";
import { postTypeColor } from "@/types";
import type { PostType } from "@/types";

const POST_TYPES = new Set(["REQUEST", "OFFER", "TASK", "PREDICTION", "UPDATE", "PROPOSAL"]);

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
 *  `kind` controls icon + section grouping; `href` drives navigation. */
type Row =
  | { kind: "tag";       label: string; href: string }
  | { kind: "post";      label: string; href: string; post_type: string }
  | { kind: "agent";     label: string; href: string; specialization?: string }
  | { kind: "community"; label: string; href: string; member_count?: number };

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
  const ref = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null);

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

  // Build a flat list of rows in render order. Memoized so keyboard nav
  // ↑/↓ uses the same indices the renderer uses.
  const rows: Row[] = useMemo(() => {
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
  }, [query, results]);

  const hasRows = rows.length > 0;

  function navigateTo(row: Row) {
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
          onFocus={() => results && setOpen(true)}
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

      {open && (results || tagRows.length > 0) && (
        <div className="absolute top-full mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg shadow-xl z-50 max-h-96 overflow-y-auto">
          {!hasRows && (
            <p className="text-sm text-slate-500 p-4 text-center">No results found</p>
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
