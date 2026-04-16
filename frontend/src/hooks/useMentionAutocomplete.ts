"use client";
import { useState, useCallback, useRef } from "react";
import { discoverAgents } from "@/lib/api";
import type { AgentMini } from "@/types";

export interface MentionState {
  query: string;
  triggerIndex: number; // index of the @ character in the string
}

export function useMentionAutocomplete(token?: string) {
  const [suggestions, setSuggestions] = useState<AgentMini[]>([]);
  const [mention, setMention] = useState<MentionState | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  /** Call this from textarea onChange/onKeyUp with current value + cursor position */
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

    clearTimeout(timerRef.current);
    if (query.length < 1) { setSuggestions([]); return; }
    timerRef.current = setTimeout(async () => {
      const results = await discoverAgents(query, token);
      setSuggestions(results.slice(0, 6));
    }, 200);
  }, [token]);

  /** Returns new text with the @mention replaced by the selected agent display_name */
  const select = useCallback((agent: AgentMini, text: string): string => {
    if (!mention) return text;
    const before = text.slice(0, mention.triggerIndex);
    const after = text.slice(mention.triggerIndex + 1 + mention.query.length);
    setMention(null);
    setSuggestions([]);
    return `${before}@${agent.display_name} ${after}`;
  }, [mention]);

  const dismiss = useCallback(() => {
    setMention(null);
    setSuggestions([]);
  }, []);

  return { suggestions, mention, detect, select, dismiss };
}
