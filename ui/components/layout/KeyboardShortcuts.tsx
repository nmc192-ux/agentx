"use client";
/**
 * Global keyboard shortcuts.
 *
 * Mirrors Bluesky / Twitter parity for power-user navigation:
 *
 *   ⌘K ─── open the command palette (handled by the sibling
 *          <CommandPalette /> component — listed here only so the
 *          help overlay surfaces it; we deliberately bail on
 *          modifier-held keys below so we don't double-handle it).
 *   /  ─── focus the search bar (or scroll to it on small screens
 *          where the SearchBar is hidden behind `sm:block` — we
 *          fall back to navigating to /explore so the key always
 *          does *something* useful).
 *   j  ─── focus the next post card in the visible list and scroll
 *          it into view (Twitter / Bluesky power-user parity). Works
 *          on any page that renders <PostCard> — feed, profile,
 *          permalink replies, hashtag, search results — because the
 *          handler queries the DOM for `[data-post-nav]` rather than
 *          owning a list itself. With nothing focused yet, picks the
 *          first post visible in the viewport (so a user who's
 *          scrolled halfway down the feed doesn't get yanked to the
 *          top on first press).
 *   k  ─── focus the previous post card (mirror of `j`).
 *   n  ─── navigate to the compose page (/posts/create). Direct deep
 *          link rather than focusing the inline composer because the
 *          inline composer only exists on /, but `n` should work from
 *          every page.
 *   g h ── go home (vim-style two-key sequence; second key within 800ms)
 *   g e ── go explore
 *   g n ── go notifications
 *   ?  ─── toggle the help overlay (also bound to `Shift+/`)
 *   Esc ── close help overlay
 *
 * The handler ignores keystrokes when the user is typing in any
 * editable element (input, textarea, [contenteditable]) — otherwise
 * `n` would try to navigate every time someone typed the letter. It
 * also ignores when a modifier key is held (cmd/ctrl/alt) so it
 * doesn't shadow browser shortcuts.
 *
 * The component renders the help overlay (a centered modal-like
 * panel listing every binding); the global event listeners live in
 * the same effect so there's exactly one keydown subscription per
 * mount of <AppShell>.
 */
import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { X } from "lucide-react";

const SHORTCUTS: { keys: string; description: string }[] = [
  { keys: "⌘ K",   description: "Command palette" },
  { keys: "j",     description: "Next post" },
  { keys: "k",     description: "Previous post" },
  { keys: "/",     description: "Focus search" },
  { keys: "n",     description: "New post" },
  { keys: "g h",   description: "Go to Home" },
  { keys: "g e",   description: "Go to Explore" },
  { keys: "g n",   description: "Go to Notifications" },
  { keys: "?",     description: "Show this help" },
  { keys: "Esc",   description: "Close dialogs" },
];

/**
 * Find the next/previous post card to focus relative to the currently
 * focused one. If nothing is focused yet (or the focused element isn't
 * a post card), pick the first card whose top edge is at or below the
 * top of the viewport — that way a user who's scrolled halfway down
 * doesn't get thrown back to post #0 on first press of `j`.
 *
 * Returns the element to focus, or null if there are no cards to
 * navigate (e.g. empty feed, error state).
 */
function pickPostCard(direction: "next" | "prev"): HTMLElement | null {
  const cards = Array.from(
    document.querySelectorAll<HTMLElement>("[data-post-nav]"),
  );
  if (cards.length === 0) return null;

  const active = document.activeElement;
  // Walk up from the active element in case focus is on a child of a
  // post card (e.g. a Reply button inside the card). The card itself
  // carries the data-post-nav attribute.
  const activeCard =
    active instanceof HTMLElement
      ? (active.closest<HTMLElement>("[data-post-nav]"))
      : null;
  const idx = activeCard ? cards.indexOf(activeCard) : -1;

  if (idx >= 0) {
    const next = direction === "next" ? idx + 1 : idx - 1;
    if (next < 0 || next >= cards.length) return cards[idx]; // edge: keep focus
    return cards[next];
  }

  // No card focused — for `j` pick the first card visible in the
  // viewport; for `k` pick the last one above/at the viewport top.
  const viewportTop = 0;
  if (direction === "next") {
    return (
      cards.find((c) => c.getBoundingClientRect().top >= viewportTop - 4) ??
      cards[0]
    );
  } else {
    // `k` from cold-start: pick the card whose bottom is highest above
    // the fold, falling back to the first card.
    const above = cards.filter(
      (c) => c.getBoundingClientRect().bottom < viewportTop + 4,
    );
    return above.length > 0 ? above[above.length - 1] : cards[0];
  }
}

/** Pretty-print a key string so each token gets its own kbd chip. */
function KeyChips({ keys }: { keys: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      {keys.split(" ").map((k, i) => (
        <kbd
          key={i}
          className="inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 rounded border border-slate-700 bg-slate-800 text-slate-200 text-xs font-mono"
        >
          {k}
        </kbd>
      ))}
    </span>
  );
}

/** True when the event target is something the user is editing. */
function isEditable(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  return false;
}

export function KeyboardShortcuts() {
  const router = useRouter();
  const [helpOpen, setHelpOpen] = useState(false);

  // Two-key combos like `g h` need a window of memory: when the user
  // hits `g` we record it and wait up to 800ms for the second key.
  const pendingPrefix = useRef<string | null>(null);
  const pendingTimer  = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearPending = useCallback(() => {
    pendingPrefix.current = null;
    if (pendingTimer.current) {
      clearTimeout(pendingTimer.current);
      pendingTimer.current = null;
    }
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't hijack typing.
      if (isEditable(e.target)) return;
      // Don't shadow browser shortcuts (cmd+/, ctrl+n, etc.).
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      // Esc always closes the help overlay (without preventing other
      // Esc-handlers — they get to run too).
      if (e.key === "Escape") {
        if (helpOpen) setHelpOpen(false);
        clearPending();
        return;
      }

      // `?` (Shift+/) opens help. Captured here so the `/` branch
      // below doesn't try to focus search on the same keystroke.
      if (e.key === "?") {
        e.preventDefault();
        setHelpOpen((v) => !v);
        clearPending();
        return;
      }

      // Two-key sequence resolution: `g <X>`.
      if (pendingPrefix.current === "g") {
        const second = e.key.toLowerCase();
        clearPending();
        if (second === "h") { e.preventDefault(); router.push("/");              return; }
        if (second === "e") { e.preventDefault(); router.push("/explore");       return; }
        if (second === "n") { e.preventDefault(); router.push("/notifications"); return; }
        // Unknown second key — fall through to single-key handling.
      }

      // Single-key shortcuts.
      switch (e.key) {
        case "j":
        case "k": {
          // Twitter / Bluesky parity: vim-style next/previous post
          // navigation across any page that renders <PostCard>. The
          // helper handles the cold-start case (no card focused yet)
          // by picking the first viewport-visible card so the keypress
          // feels grounded rather than yanking the user to the top.
          const target = pickPostCard(e.key === "j" ? "next" : "prev");
          if (!target) return;
          e.preventDefault();
          target.focus({ preventScroll: true });
          // Use scrollIntoView with `block: "nearest"` so cards already
          // mid-viewport don't jump — only off-screen ones recenter.
          target.scrollIntoView({ block: "nearest", behavior: "smooth" });
          return;
        }
        case "/": {
          e.preventDefault();
          // Try to find the search input. If it's hidden (mobile, where
          // SearchBar lives behind `hidden sm:block`), navigate to
          // /explore so the user can still discover content.
          const el = document.querySelector<HTMLInputElement>(
            "input[data-search-input]",
          );
          if (el && el.offsetParent !== null) {
            el.focus();
            el.select();
          } else {
            router.push("/explore");
          }
          return;
        }
        case "n": {
          e.preventDefault();
          router.push("/posts/create");
          return;
        }
        case "g": {
          // Start of a two-key sequence — record and wait.
          pendingPrefix.current = "g";
          if (pendingTimer.current) clearTimeout(pendingTimer.current);
          pendingTimer.current = setTimeout(clearPending, 800);
          return;
        }
      }
    };

    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      clearPending();
    };
  }, [router, helpOpen, clearPending]);

  if (!helpOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      onClick={() => setHelpOpen(false)}
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative w-full max-w-md bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-slate-100">
            Keyboard shortcuts
          </h2>
          <button
            type="button"
            onClick={() => setHelpOpen(false)}
            className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
        <ul className="p-5 space-y-3">
          {SHORTCUTS.map((s) => (
            <li
              key={s.keys}
              className="flex items-center justify-between gap-4"
            >
              <span className="text-sm text-slate-300">{s.description}</span>
              <KeyChips keys={s.keys} />
            </li>
          ))}
        </ul>
        <p className="px-5 pb-4 text-[11px] text-slate-500">
          Press <kbd className="font-mono">?</kbd> any time to toggle this panel.
        </p>
      </div>
    </div>
  );
}
