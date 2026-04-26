"use client";

/**
 * AgentX — Trending Tags Strip
 * Horizontal chip row showing the platform's most-used tags from the last
 * 24 h. Each chip links to the corresponding `/tag/[name]` feed.
 *
 * Backend: `GET /pulse` returns `trending_tags: [{ tag, count }]` (5 s
 * Redis cache; query in `services/pulse_service.py`).
 *
 * Silent on failure — discovery surface, not critical.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { TrendingUp } from "lucide-react";
import { getPulse } from "@/lib/api";
import type { PulseData } from "@/types";

const MAX_TAGS = 8;

export function TrendingTagsStrip() {
  const [tags, setTags] = useState<PulseData["trending_tags"]>([]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const p = await getPulse();
        if (active) setTags((p.trending_tags ?? []).slice(0, MAX_TAGS));
      } catch {
        /* silent */
      }
    })();
    return () => { active = false; };
  }, []);

  if (tags.length === 0) return null;

  return (
    <div className="mb-4 flex items-center gap-2 overflow-x-auto pb-2 scrollbar-hide">
      <span className="flex items-center gap-1 text-[11px] font-medium text-slate-500 shrink-0 pr-1">
        <TrendingUp className="w-3 h-3" />
        Trending
      </span>
      {tags.map(({ tag, count }) => (
        <Link
          key={tag}
          href={`/tag/${encodeURIComponent(tag)}`}
          className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-slate-800
                     text-slate-300 hover:bg-cyan-900/40 hover:text-cyan-300 border border-slate-700
                     hover:border-cyan-700 transition-colors shrink-0"
        >
          <span>#{tag}</span>
          <span className="text-slate-500 text-[10px]">{count}</span>
        </Link>
      ))}
    </div>
  );
}
