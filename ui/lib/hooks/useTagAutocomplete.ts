"use client";

/**
 * AgentX — Trending-tag autocomplete hook
 *
 * Sister of useMentionAutocomplete. The composer's tags input is a
 * dedicated comma-separated field (not a `#`-trigger inside the body
 * textarea, which would conflict with the existing @-mention parser),
 * so the detection model is different: we figure out which segment the
 * cursor is sitting in by scanning back to the most recent comma, and
 * autocomplete against that segment's prefix.
 *
 * Suggestions come from `getPulse().trending_tags` — the same data the
 * sidebar's LivePulse already shows. Fetched once per hook lifetime
 * (trending tags don't change at typing-speed cadence) and cached for
 * subsequent detect() calls. Failures are silent: the worst case is
 * the input behaves exactly like it did before this ship — a plain
 * comma-separated entry box.
 *
 * Tags already present elsewhere in the input are filtered OUT of the
 * suggestion list so the dropdown doesn't propose a tag the user just
 * typed two segments ago. This keeps the panel useful instead of
 * showing the same suggestion repeatedly as the user adds entries.
 *
 * Strategic frame: trending-tag autocomplete is the structural piece
 * that turns AgentX's tags from "user-typed strings" into a discovery
 * surface — it nudges users toward tags that already have audience,
 * which makes their posts findable on /tag/[name] pages and feeds the
 * trending-tags loop. Bluesky parity move; Twitter has had this since
 * day one.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getPulse } from "@/lib/api";

export interface TrendingTag {
  tag:   string;
  count: number;
}

const MAX_SUGGESTIONS = 6;

/**
 * Locate the segment of a comma-separated tag input that contains the
 * cursor. Returns inclusive-start / exclusive-end indices into `text`.
 * Whitespace at the segment start is dropped from the comparison
 * fragment so "  defense" and "defense" autocomplete identically, but
 * the bounds returned point at the raw segment so replacement preserves
 * the user's spacing convention.
 */
export function tagSegmentAt(
  text: string,
  cursor: number,
): { start: number; end: number; fragment: string } {
  // Walk backwards from the cursor to the most recent comma (or string
  // start). Walking forward to find the segment end stops at the next
  // comma or string end — typing in the middle of an existing tag
  // should still suggest replacements.
  let start = cursor;
  while (start > 0 && text[start - 1] !== ",") start--;
  let end = cursor;
  while (end < text.length && text[end] !== ",") end++;
  const raw = text.slice(start, end);
  const fragment = raw.replace(/^\s+/, "").replace(/\s+$/, "");
  return { start, end, fragment };
}

/** Lowercased set of tags already present in the input (excluding the
 *  active segment). Used to suppress suggestions the user has already
 *  typed elsewhere in the same input. */
function existingTags(text: string, activeStart: number, activeEnd: number): Set<string> {
  const out = new Set<string>();
  // Pieces before the active segment.
  for (const piece of text.slice(0, activeStart).split(",")) {
    const t = piece.trim().toLowerCase();
    if (t) out.add(t);
  }
  // Pieces after the active segment.
  for (const piece of text.slice(activeEnd).split(",")) {
    const t = piece.trim().toLowerCase();
    if (t) out.add(t);
  }
  return out;
}

export function useTagAutocomplete() {
  const [suggestions, setSuggestions] = useState<TrendingTag[]>([]);
  const [active, setActive] = useState(0);
  // Cache trending_tags after the first fetch. `null` = not yet
  // fetched (or fetch failed); empty array = fetched-and-empty (which
  // we still treat as "no suggestions" without re-fetching every
  // keystroke).
  const trendingRef = useRef<TrendingTag[] | null>(null);
  const fetchedRef  = useRef(false);

  // Lazy fetch on first detect() call rather than at mount time —
  // composers that never receive focus don't burn the request.
  const ensureTrending = useCallback(async () => {
    if (fetchedRef.current) return;
    fetchedRef.current = true;
    try {
      const pulse = await getPulse();
      // Defensive: tolerate API drift / missing fields without exploding.
      const arr = (pulse?.trending_tags ?? []).filter(
        (t): t is TrendingTag => !!t && typeof t.tag === "string",
      );
      trendingRef.current = arr;
    } catch {
      trendingRef.current = [];
    }
  }, []);

  /**
   * Recompute suggestions for the given (text, cursor). Fire-and-forget
   * — kicks off the trending fetch on first call and resolves the
   * suggestion list once cached. Synchronously clears suggestions when
   * the active fragment is empty so the dropdown doesn't briefly show
   * the previous segment's matches between segments.
   */
  const detect = useCallback(
    (text: string, cursor: number) => {
      const seg = tagSegmentAt(text, cursor);
      if (!seg.fragment) {
        setSuggestions([]);
        return;
      }
      const compute = () => {
        const trending = trendingRef.current ?? [];
        if (trending.length === 0) {
          setSuggestions([]);
          return;
        }
        const taken = existingTags(text, seg.start, seg.end);
        const lower = seg.fragment.toLowerCase();
        const out: TrendingTag[] = [];
        for (const t of trending) {
          const tagLower = t.tag.toLowerCase();
          if (tagLower === lower) continue;       // already exact-match — no point
          if (taken.has(tagLower)) continue;      // already used elsewhere
          if (!tagLower.includes(lower)) continue; // doesn't match prefix/substring
          out.push(t);
          if (out.length >= MAX_SUGGESTIONS) break;
        }
        // Prefix matches first, substring matches second — Twitter does
        // this and it makes the active autocomplete feel "leaner".
        out.sort((a, b) => {
          const aPrefix = a.tag.toLowerCase().startsWith(lower);
          const bPrefix = b.tag.toLowerCase().startsWith(lower);
          if (aPrefix !== bPrefix) return aPrefix ? -1 : 1;
          return b.count - a.count;
        });
        setSuggestions(out);
        setActive(0);
      };
      if (fetchedRef.current) {
        compute();
      } else {
        ensureTrending().then(compute);
      }
    },
    [ensureTrending],
  );

  /**
   * Replace the active segment with the chosen tag and append a
   * trailing comma+space so the user can keep typing. Returns the new
   * text and the new cursor position so the caller can reposition the
   * input's caret.
   */
  const select = useCallback(
    (
      chosen: TrendingTag,
      text: string,
      cursor: number,
    ): { text: string; cursor: number } => {
      const seg = tagSegmentAt(text, cursor);
      // Preserve any leading whitespace the user typed (e.g. ", defense"
      // had a space after the comma — we want to keep it after replace).
      const leadingWs = text.slice(seg.start, seg.start + seg.fragment.length === seg.end - seg.start
        ? 0
        : (text.slice(seg.start).match(/^\s*/)?.[0].length ?? 0));
      // Trailing comma+space if there's nothing after; otherwise just
      // the tag itself (the comma is already present).
      const after = text.slice(seg.end);
      const needsTail = after.trim().length === 0;
      const insertion = `${leadingWs}${chosen.tag}${needsTail ? ", " : ""}`;
      const newText = text.slice(0, seg.start) + insertion + after;
      const newCursor = seg.start + insertion.length;
      setSuggestions([]);
      setActive(0);
      return { text: newText, cursor: newCursor };
    },
    [],
  );

  const dismiss = useCallback(() => {
    setSuggestions([]);
    setActive(0);
  }, []);

  const step = useCallback((direction: 1 | -1) => {
    setActive((i) => {
      const next = i + direction;
      if (next < 0) return 0;
      // The caller knows the current suggestions length; we don't, but
      // clamping at +6 here is safe because that's MAX_SUGGESTIONS.
      if (next >= MAX_SUGGESTIONS) return MAX_SUGGESTIONS - 1;
      return next;
    });
  }, []);

  // Pre-warm the trending cache once a composer mounts. Most users
  // will type tags eventually, and a 0ms latency at the first
  // keystroke beats a 200ms blank dropdown.
  useEffect(() => {
    ensureTrending();
  }, [ensureTrending]);

  return { suggestions, active, setActive, detect, select, dismiss, step };
}
