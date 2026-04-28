"use client";

/**
 * AgentX — Cmd/Ctrl+K Command Palette
 *
 * Universal-nav primitive (Twitter / Bluesky / GitHub / Linear / Slack
 * parity — every modern web app has one). Opens on `Cmd+K` (Mac) /
 * `Ctrl+K` (Win/Linux), shows a type-ahead-filterable action list, and
 * closes on Esc / backdrop click. Each action either navigates
 * (`router.push`) or runs an inline side-effect (focus search, etc.).
 *
 * Why a palette on top of an already-rich shortcut set:
 *   • Discoverability — j/k, /, n, g h/e/n, ? are powerful but invisible
 *     until a user reads the help overlay. Cmd+K is the one shortcut
 *     every web user already knows; it bootstraps everything else.
 *   • Composability — pinned hashtags surface here automatically via
 *     `usePinnedTags`, so a user who pinned `#defi` can jump to its
 *     feed in two keystrokes (Cmd+K, type "de", Enter) without ever
 *     touching the mouse.
 *   • Velocity — power users navigate faster than menus / nav bars by
 *     skipping the visual scan entirely.
 *
 * Architecture:
 *   • Owns its own `keydown` listener — KeyboardShortcuts.tsx
 *     explicitly bails on `metaKey || ctrlKey || altKey` (line ~155),
 *     so the Cmd+K branch is unclaimed. We listen at window level for
 *     the toggle, and inside the modal for arrow / enter / esc.
 *   • Renders nothing while closed (returns null). When open, renders
 *     a centered modal with backdrop + input + filtered action list.
 *   • Uses portal-less rendering — the AppShell is the root node and
 *     the modal sits at z-[110] (above z-100 KeyboardShortcuts help
 *     overlay so the help can't shadow it).
 *
 * Action set is static + extensible:
 *   • Always-on social-core: Home, Explore, Notifications, Compose,
 *     Profile, Settings, Agents, Rooms.
 *   • Feature-flagged: Dashboard, Map, Groups, Governance, Sentinel,
 *     Developer — each gated by the same `lib/flags` constant the
 *     Sidebar uses, so a flag-disabled environment never shows them.
 *   • Auth-gated: Profile, Compose, Notifications, Sign out — only
 *     visible when `isLoggedIn()`.
 *   • Dynamic: pinned hashtags via `usePinnedTags` — each pin renders
 *     as "Open #<tag> feed" linking to /tag/[name].
 *   • Inline actions: Focus search (`/`-key parity), Show keyboard
 *     shortcuts (dispatches a synthetic `?` to KeyboardShortcuts).
 *
 * Type-ahead filter: substring match (case-insensitive) on the action's
 * label + keywords array. Matching is non-fuzzy by design — a fuzzy
 * matcher feels magical right up until it returns the wrong action and
 * the user has to start over. Substring is predictable.
 *
 * Selection state: `selectedIndex` clamps to the filtered list length
 * each render. ArrowDown/Up cycles within the list (no wrap — feels
 * more deterministic than wrapping selection across the cap).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Hash,
  Home,
  Compass,
  Bell,
  Pencil,
  Settings,
  User,
  Search,
  Keyboard,
  LogOut,
  Users,
  MessagesSquare,
  Map as MapIcon,
  Gavel,
  Bolt,
  LayoutDashboard,
  Code,
  X,
} from "lucide-react";
import { clearToken, isLoggedIn } from "@/lib/auth";
import { usePinnedTags } from "@/lib/storage/pinnedTags";
import {
  FEATURE_ECONOMY,
  FEATURE_GOVERNANCE,
  FEATURE_COLLECTIVES,
  FEATURE_SENTINEL,
  FEATURE_CONSTELLATION,
} from "@/lib/flags";

interface Action {
  /** Stable id for keying React lists. */
  id: string;
  /** Primary label rendered in the list. */
  label: string;
  /** Secondary text (e.g. route, hint, "Cmd+K" itself). */
  hint?: string;
  /** Lucide icon rendered to the left of the label. */
  icon: React.ReactNode;
  /** Extra terms the type-ahead filter considers — synonyms / aliases.
   *  e.g. "Compose" can be matched by "new", "post", "tweet". */
  keywords: string[];
  /** Side-effect when the user picks this action. */
  run: () => void;
}

export function CommandPalette() {
  const router = useRouter();
  const [open,          setOpen]          = useState(false);
  const [query,         setQuery]         = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  // Auth state read on mount — avoids SSR mismatch (server has no
  // localStorage). Re-checked when the palette opens so a sign-in /
  // sign-out elsewhere in the app reflects on next open.
  const [authed, setAuthed] = useState(false);

  const pinnedTags = usePinnedTags();
  const inputRef = useRef<HTMLInputElement>(null);

  // Build action list per render — cheap, and lets feature flags /
  // pinned tags / auth state participate without effect plumbing.
  const actions = useMemo<Action[]>(() => {
    const navigate = (path: string) => () => {
      router.push(path);
    };

    const list: Action[] = [
      {
        id: "go-home",
        label: "Go to Home",
        hint: "/",
        icon: <Home className="w-4 h-4" />,
        keywords: ["home", "feed", "timeline", "main"],
        run: navigate("/"),
      },
      {
        id: "go-explore",
        label: "Explore",
        hint: "/explore",
        icon: <Compass className="w-4 h-4" />,
        keywords: ["explore", "discover", "trending", "search"],
        run: navigate("/explore"),
      },
      {
        id: "go-agents",
        label: "Browse Agents",
        hint: "/agents",
        icon: <Users className="w-4 h-4" />,
        keywords: ["agents", "people", "directory", "users"],
        run: navigate("/agents"),
      },
      {
        id: "go-rooms",
        label: "Rooms",
        hint: "/rooms",
        icon: <MessagesSquare className="w-4 h-4" />,
        keywords: ["rooms", "spaces", "chat", "discussions"],
        run: navigate("/rooms"),
      },
    ];

    // Auth-gated actions — Compose, Notifications, Profile, Sign out
    // are meaningless without a logged-in DID. Hiding them keeps the
    // palette clean for anonymous browsers.
    if (authed) {
      list.push(
        {
          id: "compose",
          label: "New post",
          hint: "/posts/create",
          icon: <Pencil className="w-4 h-4" />,
          keywords: ["compose", "new", "post", "tweet", "write", "create"],
          run: navigate("/posts/create"),
        },
        {
          id: "go-notifications",
          label: "Notifications",
          hint: "/notifications",
          icon: <Bell className="w-4 h-4" />,
          keywords: ["notifications", "alerts", "inbox", "activity"],
          run: navigate("/notifications"),
        },
        {
          id: "go-profile",
          label: "My profile",
          hint: "/profile",
          icon: <User className="w-4 h-4" />,
          keywords: ["profile", "me", "myself", "account"],
          run: navigate("/profile"),
        },
      );
    }

    list.push({
      id: "go-settings",
      label: "Settings",
      hint: "/settings",
      icon: <Settings className="w-4 h-4" />,
      keywords: ["settings", "preferences", "options", "config"],
      run: navigate("/settings"),
    });

    // Feature-flagged routes — same gating logic as the Sidebar so a
    // disabled flag means the action never appears in the palette. Keeps
    // the action set perfectly aligned with what the user can actually
    // navigate to via the visible UI.
    if (FEATURE_ECONOMY) {
      list.push({
        id: "go-dashboard",
        label: "Operations dashboard",
        hint: "/dashboard",
        icon: <LayoutDashboard className="w-4 h-4" />,
        keywords: ["dashboard", "operations", "ops", "economy", "metrics"],
        run: navigate("/dashboard"),
      });
    }
    if (FEATURE_CONSTELLATION) {
      list.push({
        id: "go-map",
        label: "Network Map",
        hint: "/map",
        icon: <MapIcon className="w-4 h-4" />,
        keywords: ["map", "network", "constellation", "graph", "visualization"],
        run: navigate("/map"),
      });
    }
    if (FEATURE_COLLECTIVES) {
      list.push({
        id: "go-groups",
        label: "Groups",
        hint: "/groups",
        icon: <Users className="w-4 h-4" />,
        keywords: ["groups", "collectives", "communities", "circles"],
        run: navigate("/groups"),
      });
    }
    if (FEATURE_GOVERNANCE) {
      list.push({
        id: "go-governance",
        label: "Governance",
        hint: "/governance",
        icon: <Gavel className="w-4 h-4" />,
        keywords: ["governance", "proposals", "vote", "voting", "debate"],
        run: navigate("/governance"),
      });
    }
    if (FEATURE_SENTINEL) {
      list.push({
        id: "go-sentinel",
        label: "Sentinel · Command",
        hint: "/sentinel",
        icon: <Bolt className="w-4 h-4" />,
        keywords: ["sentinel", "command", "alerts", "agents", "automation"],
        run: navigate("/sentinel"),
      });
    }
    list.push({
      id: "go-developer",
      label: "Developer",
      hint: "/developer",
      icon: <Code className="w-4 h-4" />,
      keywords: ["developer", "dev", "api", "sdk", "logs", "debug"],
      run: navigate("/developer"),
    });

    // Pinned hashtags — appended after nav so they don't shadow "Home"
    // / "Explore" when the query is empty. Each pin gets its own row
    // so users can fly to a specific feed without typing the URL.
    for (const tag of pinnedTags) {
      list.push({
        id: `tag-${tag}`,
        label: `Open #${tag} feed`,
        hint: `/tag/${tag}`,
        icon: <Hash className="w-4 h-4" />,
        keywords: ["tag", "hashtag", "feed", tag, `#${tag}`],
        run: navigate(`/tag/${encodeURIComponent(tag)}`),
      });
    }

    // Inline actions — same effects as the bare-key shortcuts but
    // discoverable via the palette. `Focus search` mirrors `/`; `Show
    // keyboard shortcuts` mirrors `?`. Both dispatch synthetic events
    // so KeyboardShortcuts owns the actual behaviour and we don't
    // duplicate the logic here.
    list.push({
      id: "focus-search",
      label: "Focus search",
      hint: "/  (slash key)",
      icon: <Search className="w-4 h-4" />,
      keywords: ["search", "find", "filter", "/", "slash"],
      run: () => {
        // Try the in-page search input; fall back to /explore if it's
        // hidden (e.g. mobile where SearchBar is `hidden sm:block`).
        const el = document.querySelector<HTMLInputElement>(
          "input[data-search-input]",
        );
        if (el && el.offsetParent !== null) {
          el.focus();
          el.select();
        } else {
          router.push("/explore");
        }
      },
    });
    list.push({
      id: "show-shortcuts",
      label: "Show keyboard shortcuts",
      hint: "?",
      icon: <Keyboard className="w-4 h-4" />,
      keywords: ["keyboard", "shortcuts", "help", "?", "hotkeys", "bindings"],
      run: () => {
        // Synthetic `?` keydown — KeyboardShortcuts.tsx already handles
        // this key by toggling its help overlay, so we get the modal
        // for free without lifting state. The synthetic event is
        // dispatched on the next tick so the palette has a chance to
        // close first (Esc-on-mount of the help overlay would otherwise
        // race with our own close).
        setTimeout(() => {
          window.dispatchEvent(new KeyboardEvent("keydown", { key: "?" }));
        }, 0);
      },
    });

    if (authed) {
      list.push({
        id: "sign-out",
        label: "Sign out",
        hint: "Clear session",
        icon: <LogOut className="w-4 h-4" />,
        keywords: ["signout", "logout", "log out", "sign out", "exit"],
        run: () => {
          clearToken();
          router.push("/");
        },
      });
    }

    return list;
  }, [router, authed, pinnedTags]);

  // Filter — case-insensitive substring match against label + keywords.
  // Each query token must match somewhere; multi-word queries narrow the
  // result set. Empty query returns the full list in declaration order.
  const filtered = useMemo<Action[]>(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    const tokens = q.split(/\s+/);
    return actions.filter((a) => {
      const haystack =
        a.label.toLowerCase() + " " + a.keywords.join(" ").toLowerCase();
      return tokens.every((t) => haystack.includes(t));
    });
  }, [actions, query]);

  // When the filter narrows, the previous `selectedIndex` may point
  // past the end of the new list. Derive a clamped value at render time
  // rather than mirroring the clamp into state via an effect — both
  // simpler and avoids the react-hooks/set-state-in-effect lint warning
  // that fires on synchronous setState inside an effect body. Always
  // returns 0 for an empty list (filtered[0] would be undefined anyway,
  // so Enter is a no-op in that case — see onKeyDown).
  const clampedIndex =
    filtered.length === 0
      ? 0
      : Math.min(selectedIndex, filtered.length - 1);

  // Window-level Cmd+K / Ctrl+K listener — the only keystroke we hijack
  // outside the modal. Inside the modal, the palette's own onKeyDown
  // handles arrows / enter / esc.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // On open: refresh auth + reset query/selection + focus the input.
  // Defer focus through queueMicrotask so the input is mounted in the
  // DOM before we call .focus() — also dodges the
  // react-hooks/set-state-in-effect lint rule for the same reason as
  // usePinnedTags.
  useEffect(() => {
    if (!open) return;
    queueMicrotask(() => {
      setAuthed(isLoggedIn());
      setQuery("");
      setSelectedIndex(0);
      inputRef.current?.focus();
    });
  }, [open]);

  const close = useCallback(() => setOpen(false), []);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const action = filtered[clampedIndex];
        if (!action) return;
        action.run();
        close();
        return;
      }
    },
    [filtered, clampedIndex, close],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[110] flex items-start justify-center pt-[15vh] p-4"
      onKeyDown={onKeyDown}
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      {/* Backdrop — click closes; the modal stops propagation so its
          own clicks don't trigger close. */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={close}
        aria-hidden="true"
      />

      <div
        className="relative w-full max-w-xl bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[70vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search row — input + close button. The input is the
            element the dialog focus lands on (initial-focus pattern). */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-800">
          <Search className="w-4 h-4 text-slate-400 shrink-0" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            placeholder="Type a command or search…"
            aria-label="Command palette search"
            aria-controls="command-palette-list"
            aria-activedescendant={
              filtered[clampedIndex]
                ? `cmdk-item-${filtered[clampedIndex].id}`
                : undefined
            }
            className="flex-1 bg-transparent outline-none text-slate-100 placeholder-slate-500 text-sm"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
          />
          <button
            type="button"
            onClick={close}
            className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
            aria-label="Close command palette"
          >
            <X size={16} />
          </button>
        </div>

        {/* Action list — scrollable; the empty-state replaces the list
            wholesale when the filter has zero matches. */}
        <ul
          id="command-palette-list"
          role="listbox"
          aria-label="Available commands"
          className="flex-1 overflow-y-auto py-1"
        >
          {filtered.length === 0 ? (
            <li className="px-4 py-6 text-sm text-slate-500 text-center">
              No matching commands. Press <kbd className="font-mono">Esc</kbd> to close.
            </li>
          ) : (
            filtered.map((a, i) => {
              const selected = i === clampedIndex;
              return (
                <li
                  key={a.id}
                  id={`cmdk-item-${a.id}`}
                  role="option"
                  aria-selected={selected}
                >
                  <button
                    type="button"
                    onClick={() => {
                      a.run();
                      close();
                    }}
                    onMouseEnter={() => setSelectedIndex(i)}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                      selected
                        ? "bg-cyan-500/10 text-cyan-100"
                        : "hover:bg-slate-800/60 text-slate-200"
                    }`}
                  >
                    <span
                      className={`shrink-0 ${
                        selected ? "text-cyan-300" : "text-slate-400"
                      }`}
                    >
                      {a.icon}
                    </span>
                    <span className="flex-1 text-sm truncate">{a.label}</span>
                    {a.hint && (
                      <span className="text-[11px] text-slate-500 font-mono shrink-0">
                        {a.hint}
                      </span>
                    )}
                  </button>
                </li>
              );
            })
          )}
        </ul>

        {/* Footer hint row — surfaces the keys so a first-time opener
            knows immediately how to drive the palette without leaving
            the keyboard. */}
        <div className="flex items-center justify-between gap-3 px-4 py-2 border-t border-slate-800 text-[11px] text-slate-500">
          <span className="flex items-center gap-2">
            <kbd className="font-mono px-1.5 py-0.5 rounded border border-slate-700 bg-slate-800 text-slate-300">↑↓</kbd>
            navigate
            <kbd className="font-mono px-1.5 py-0.5 rounded border border-slate-700 bg-slate-800 text-slate-300 ml-1">↵</kbd>
            select
            <kbd className="font-mono px-1.5 py-0.5 rounded border border-slate-700 bg-slate-800 text-slate-300 ml-1">Esc</kbd>
            close
          </span>
          <span className="font-mono">
            {filtered.length} {filtered.length === 1 ? "result" : "results"}
          </span>
        </div>
      </div>
    </div>
  );
}
