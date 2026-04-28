"use client";

/**
 * AgentX — In-textarea #hashtag autocomplete hook
 *
 * Sister to useMentionAutocomplete (which does `@<slug>` cursor-triggers
 * inside the post body) and useTagAutocomplete (which does comma-segment
 * detection inside the dedicated tags input). This hook fills the third
 * cell of that table: cursor-triggered `#<query>` matching *inside* the
 * post body textarea — the surface Twitter / Bluesky have had since day
 * one.
 *
 * Why a third hook rather than overloading either of the existing two?
 *
 *   • useMentionAutocomplete fetches per-keystroke from `discoverAgents`
 *     — the agent index is too large to ship to the client. Trending
 *     tags are a fixed, ~10-item list from `getPulse()`, so we want the
 *     "fetch once, filter in-memory" model. Different I/O shapes.
 *
 *   • useTagAutocomplete uses a comma-segment detection model (which
 *     segment is the cursor in?), not a `#`-trigger model. Conceptually
 *     unrelated; reusing it would force awkward dual-mode logic.
 *
 * The detection regex matches what richText.tsx's RICH_RE accepts so
 * "what gets autocompleted" and "what gets linkified after posting"
 * stay aligned: `#` followed by 1–32 chars of `[\w-]`. We intentionally
 * skip the trigger when the `#` follows an alphanumeric character (e.g.
 * `id#42` shouldn't fire) — same behaviour as useMentionAutocomplete's
 * implicit anchor at the start of a word.
 *
 * Trending tags come from the same getPulse() cache that LivePulse and
 * the tags-input autocomplete use; the hook lazily warms the cache on
 * first detect() call (and pre-warms on mount, since a focused composer
 * almost always ends up typing). Failures are silent: the worst case is
 * the textarea behaves exactly like it did before — no autocomplete,
 * just plain text. richText still linkifies the rendered post.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getPulse } from "@/lib/api";

export interface HashtagSuggestion {
  tag:   string;
  count: number;
}

export interface HashtagState {
  query:        string;
  triggerIndex: number;
}

const MAX_SUGGESTIONS = 6;

/**
 * Locate a `#<query>` trigger ending exactly at `cursor`. Returns null
 * when the cursor isn't inside a hashtag — the dropdown should close.
 *
 * Anchoring rule: the `#` must be at string start or preceded by a
 * non-`[\w-]` character. Without this, typing inside an email-like
 * "user#handle" would falsely fire the dropdown.
 */
function detectHashtagAt(
  text: string,
  cursor: number,
): HashtagState | null {
  const before = text.slice(0, cursor);
  const m = before.match(/(^|[^\w-])#([\w-]{0,32})$/);
  if (!m) return null;
  const query = m[2];
  // m.index points at the start of the FULL match including the prefix
  // char; the `#` itself sits one position later when the prefix matched
  // a real char (m[1].length === 1) or at m.index when prefix was "".
  const triggerIndex = (m.index ?? 0) + (m[1]?.length ?? 0);
  return { query, triggerIndex };
}

export function useHashtagAutocomplete() {
  const [suggestions, setSuggestions] = useState<HashtagSuggestion[]>([]);
  const [hashtag, setHashtag] = useState<HashtagState | null>(null);
  const [active, setActive] = useState(0);

  const trendingRef = useRef<HashtagSuggestion[] | null>(null);
  const fetchedRef  = useRef(false);

  // Lazy fetch — composers that never receive focus don't burn the
  // request. ensureTrending is also pre-warmed in a mount effect below
  // so the first keystroke has cached data ready.
  const ensureTrending = useCallback(async () => {
    if (fetchedRef.current) return;
    fetchedRef.current = true;
    try {
      const pulse = await getPulse();
      const arr = (pulse?.trending_tags ?? []).filter(
        (t): t is HashtagSuggestion =>
          !!t && typeof t.tag === "string" && typeof t.count === "number",
      );
      trendingRef.current = arr;
    } catch {
      trendingRef.current = [];
    }
  }, []);

  /**
   * Recompute hashtag state + suggestions for (text, cursor). Synchronous
   * for the no-trigger / empty-query cases (clears the panel) and
   * asynchronous only when we still need to hydrate the trending cache.
   */
  const detect = useCallback(
    (text: string, cursor: number) => {
      const state = detectHashtagAt(text, cursor);
      if (!state) {
        setHashtag(null);
        setSuggestions([]);
        return;
      }
      setHashtag(state);

      const compute = () => {
        const trending = trendingRef.current ?? [];
        if (trending.length === 0) {
          setSuggestions([]);
          return;
        }
        const lower = state.query.toLowerCase();
        // Empty query (just typed `#` with no chars after) — show the
        // top trending tags as a discovery surface. Twitter / Bluesky
        // both do this; we surface 6.
        const filtered = lower.length === 0
          ? trending.slice()
          : trending.filter((t) => t.tag.toLowerCase().includes(lower));
        // Prefix matches first, then substring matches, then by count.
        // Same ranking as useTagAutocomplete so the two surfaces feel
        // like one feature.
        filtered.sort((a, b) => {
          const aPrefix = a.tag.toLowerCase().startsWith(lower);
          const bPrefix = b.tag.toLowerCase().startsWith(lower);
          if (aPrefix !== bPrefix) return aPrefix ? -1 : 1;
          return b.count - a.count;
        });
        setSuggestions(filtered.slice(0, MAX_SUGGESTIONS));
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
   * Replace the active `#<query>` trigger with the chosen tag and
   * append a trailing space so the user can keep typing. Returns the
   * new text and the cursor position to set on the textarea.
   */
  const select = useCallback(
    (
      chosen: HashtagSuggestion,
      text: string,
    ): { text: string; cursor: number } => {
      if (!hashtag) return { text, cursor: text.length };
      const before = text.slice(0, hashtag.triggerIndex);
      const after = text.slice(hashtag.triggerIndex + 1 + hashtag.query.length);
      // Trailing space keeps typing flowing; richText still parses the
      // hashtag correctly because the regex stops at non-`[\w-]`.
      const insertion = `#${chosen.tag} `;
      const newText = before + insertion + after;
      const newCursor = before.length + insertion.length;
      setHashtag(null);
      setSuggestions([]);
      setActive(0);
      return { text: newText, cursor: newCursor };
    },
    [hashtag],
  );

  const dismiss = useCallback(() => {
    setHashtag(null);
    setSuggestions([]);
    setActive(0);
  }, []);

  const step = useCallback((direction: 1 | -1) => {
    setActive((i) => {
      const next = i + direction;
      if (next < 0) return 0;
      if (next >= MAX_SUGGESTIONS) return MAX_SUGGESTIONS - 1;
      return next;
    });
  }, []);

  // Pre-warm the trending cache so the first keystroke after focus has
  // suggestions ready. Cheap (one HTTP call, no per-keystroke cost
  // afterward) and the LivePulse sidebar likely already cached the
  // result on the same page.
  useEffect(() => {
    ensureTrending();
  }, [ensureTrending]);

  return {
    suggestions,
    hashtag,
    active,
    setActive,
    detect,
    select,
    dismiss,
    step,
  };
}
