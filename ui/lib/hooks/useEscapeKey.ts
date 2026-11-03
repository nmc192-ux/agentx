"use client";

/**
 * AgentX — useEscapeKey
 *
 * Calls `onEscape` when Escape is pressed anywhere in the document while
 * the calling component is mounted. Dialogs use it so a keyboard user can
 * always close them (Layer 1 S7-3 accessibility pass).
 */
import { useEffect } from "react";

export function useEscapeKey(onEscape: () => void, enabled = true): void {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onEscape();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onEscape, enabled]);
}
