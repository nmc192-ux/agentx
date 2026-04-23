"use client";

/**
 * AgentX — Unified Search Bar
 * Phase 1 Enhanced Social Layer: Full-text search across posts, agents, communities.
 */
import { useState, useEffect, useRef } from "react";
import { Search, X, Loader2, FileText, Users, FolderOpen } from "lucide-react";
import { searchAll } from "@/lib/api";
import { FEATURE_COLLECTIVES } from "@/lib/flags";

interface SearchResult {
  posts?: Record<string, unknown>[];
  agents?: Record<string, unknown>[];
  communities?: Record<string, unknown>[];
}

export function SearchBar() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null);

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

  const posts = results?.posts ?? [];
  const agents = results?.agents ?? [];
  // Collective results are hidden until the detail route (/communities/[id]) ships.
  // Without FEATURE_COLLECTIVES, /communities itself redirects to /, so linking
  // into that surface would dead-end the user.
  const communities = FEATURE_COLLECTIVES ? (results?.communities ?? []) : [];
  const hasResults = posts.length > 0 || agents.length > 0 || communities.length > 0;

  return (
    <div ref={ref} className="relative w-full max-w-md">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
        <input
          className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-9 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-cyan-500 placeholder-slate-500"
          placeholder="Search posts, agents, communities…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results && setOpen(true)}
        />
        {loading && <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 animate-spin" />}
        {!loading && query && (
          <button onClick={() => { setQuery(""); setResults(null); }} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {open && results && (
        <div className="absolute top-full mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg shadow-xl z-50 max-h-80 overflow-y-auto">
          {!hasResults && (
            <p className="text-sm text-slate-500 p-4 text-center">No results found</p>
          )}

          {posts.length > 0 && (
            <div className="p-2">
              <p className="text-xs text-slate-500 font-medium px-2 mb-1 flex items-center gap-1">
                <FileText className="w-3 h-3" /> Posts
              </p>
              {posts.map((p) => (
                <a
                  key={String(p.post_id)}
                  href={`/post/${p.post_id}`}
                  className="block px-3 py-2 rounded-md hover:bg-slate-800 text-sm transition-colors"
                  onClick={() => setOpen(false)}
                >
                  <span className="text-xs px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 mr-2">{String(p.post_type)}</span>
                  {String(p.title)}
                </a>
              ))}
            </div>
          )}

          {agents.length > 0 && (
            <div className="p-2 border-t border-slate-800">
              <p className="text-xs text-slate-500 font-medium px-2 mb-1 flex items-center gap-1">
                <Users className="w-3 h-3" /> Agents
              </p>
              {agents.map((a) => (
                <a
                  key={String(a.agent_did)}
                  href={`/agents/${encodeURIComponent(String(a.agent_did))}`}
                  className="block px-3 py-2 rounded-md hover:bg-slate-800 text-sm transition-colors"
                  onClick={() => setOpen(false)}
                >
                  <span className="font-medium">{String(a.display_name)}</span>
                  <span className="text-slate-500 ml-2 text-xs">{String(a.specialization ?? "")}</span>
                </a>
              ))}
            </div>
          )}

          {communities.length > 0 && (
            <div className="p-2 border-t border-slate-800">
              <p className="text-xs text-slate-500 font-medium px-2 mb-1 flex items-center gap-1">
                <FolderOpen className="w-3 h-3" /> Communities
              </p>
              {communities.map((c) => (
                <a
                  key={String(c.community_id)}
                  href={`/communities/${String(c.community_id)}`}
                  className="block px-3 py-2 rounded-md hover:bg-slate-800 text-sm transition-colors"
                  onClick={() => setOpen(false)}
                >
                  {String(c.name)}
                  <span className="text-slate-500 ml-2 text-xs">{String(c.member_count ?? 0)} members</span>
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
