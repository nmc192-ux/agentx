"use client";
import { useState, useCallback, useRef } from "react";
import { discoverAgents } from "@/lib/api";
import type { AgentMini } from "@/types";

export interface MentionState {
  query: string;
  triggerIndex: number;
}

/**
 * @mention autocomplete hook — detects `@<query>` before cursor, debounce-queries
 * /agents/discover, and returns the state needed to render a dropdown.
 *
 * Adapted from /AgentX/frontend to the ui/ app (plain fetch, no react-query).
 */
export function useMentionAutocomplete() {
  const [suggestions, setSuggestions] = useState<AgentMini[]>([]);
  const [mention, setMention] = useState<MentionState | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const detect = useCallback((text: string, cursor: number) => {
    const before = text.slice(0, cursor);
    const match = before.match(/@([\w-]{0,30})$/);
    if (!match) {
      setMention(null);
      setSuggestions([]);
      return;
    }
    const query = match[1];
    const triggerIndex = before.length - match[0].length;
    setMention({ query, triggerIndex });

    if (timerRef.current) clearTimeout(timerRef.current);
    if (query.length < 1) {
      setSuggestions([]);
      return;
    }
    timerRef.current = setTimeout(async () => {
      try {
        const results = await discoverAgents(query);
        // results is Record<string, unknown>[]; shape-coerce into AgentMini
        const mini: AgentMini[] = (results as Record<string, unknown>[])
          .slice(0, 6)
          .map((r) => ({
            agent_did:       String(r.agent_did),
            display_name:    String(r.display_name ?? r.agent_did),
            trust_score:     Number(r.trust_score ?? 0),
            tier:            (r.tier as AgentMini["tier"]) ?? "STANDARD",
            bio:             (r.bio as string | null | undefined) ?? null,
            followers_count: Number(r.followers_count ?? 0),
            following_count: Number(r.following_count ?? 0),
          }));
        setSuggestions(mini);
      } catch {
        setSuggestions([]);
      }
    }, 200);
  }, []);

  const select = useCallback(
    (agent: AgentMini, text: string): string => {
      if (!mention) return text;
      const before = text.slice(0, mention.triggerIndex);
      const after = text.slice(mention.triggerIndex + 1 + mention.query.length);
      setMention(null);
      setSuggestions([]);
      return `${before}@${agent.display_name} ${after}`;
    },
    [mention],
  );

  const dismiss = useCallback(() => {
    setMention(null);
    setSuggestions([]);
  }, []);

  return { suggestions, mention, detect, select, dismiss };
}
