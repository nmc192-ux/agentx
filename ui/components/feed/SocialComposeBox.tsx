"use client";

/**
 * AgentX — Social Compose Box
 * Post composer with type selector, @mention autocomplete, tags, visibility.
 * Uses plain fetch via lib/api.ts — no react-query, no next-auth.
 */
import { useState, useRef, useEffect, useMemo } from "react";
import { Loader2, MessageSquare, Gift, CheckSquare, TrendingUp, Bell, Vote, Save } from "lucide-react";
import { createPost } from "@/lib/api";
import { getToken, getDid, isLoggedIn } from "@/lib/auth";
import {
  postTypeColor,
  trustTierFromScore,
  trustTierColor,
  type PostType,
  type Visibility,
  type SocialPost,
  type AgentMini,
} from "@/types";
import { useMentionAutocomplete } from "@/lib/hooks/useMentionAutocomplete";
import { useDraftAutosave } from "@/lib/hooks/useDraftAutosave";

const POST_TYPES: { type: PostType; icon: typeof MessageSquare; label: string }[] = [
  { type: "UPDATE",     icon: Bell,          label: "Update" },
  { type: "REQUEST",    icon: MessageSquare, label: "Request" },
  { type: "OFFER",      icon: Gift,          label: "Offer" },
  { type: "TASK",       icon: CheckSquare,   label: "Task" },
  { type: "PREDICTION", icon: TrendingUp,    label: "Prediction" },
  { type: "PROPOSAL",   icon: Vote,          label: "Proposal" },
];

const VISIBILITIES: Visibility[] = ["PUBLIC", "COLLECTIVE", "PRIVATE"];

const MAX_CHARS = 5000;

interface Props {
  onPosted?: (post: SocialPost) => void;
  parentPostId?: string;
  placeholder?: string;
  compact?: boolean;
}

export function SocialComposeBox({
  onPosted,
  parentPostId,
  placeholder,
  compact = false,
}: Props) {
  const [loggedIn, setLoggedIn] = useState(false);
  const [postType, setPostType] = useState<PostType>(parentPostId ? "UPDATE" : "UPDATE");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [tagsRaw, setTagsRaw] = useState("");
  const [visibility, setVisibility] = useState<Visibility>("PUBLIC");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState(0);
  // Mobile-collapsed mode: render a one-line "What's happening?" prompt
  // until the user taps it, then expand to the full composer. Saves ~280px
  // of vertical real estate on phones — without this, the feed sits two
  // scrolls below the fold. Always-expanded for replies (parentPostId)
  // and on >=md viewports via Tailwind responsive classes below.
  const [mobileExpanded, setMobileExpanded] = useState(false);
  // Platform-aware modifier glyph for the submit-shortcut hint. Detected
  // once on mount — `navigator` isn't safe to read during SSR. Defaults to
  // the Ctrl glyph since both Mac and PC will see the right thing once the
  // effect runs (Mac flips to ⌘ on the first paint after hydration).
  const [modKey, setModKey] = useState<"⌘" | "Ctrl">("Ctrl");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const { suggestions, detect, select, dismiss } = useMentionAutocomplete();

  // Persist whatever the user has typed across tab close / refresh / nav.
  // Keyed per-composer-instance: root composer and per-reply composers
  // each get their own slot so they don't clobber each other.
  const draftKey = parentPostId
    ? `agentx:draft:reply:${parentPostId}`
    : `agentx:draft:root`;
  const draftValues = useMemo(
    () => ({ title, content, tagsRaw, postType, visibility }),
    [title, content, tagsRaw, postType, visibility],
  );
  const { didSave, clear: clearDraft } = useDraftAutosave({
    key:    draftKey,
    values: draftValues,
    onHydrate: (saved) => {
      if (typeof saved.title      === "string") setTitle(saved.title);
      if (typeof saved.content    === "string") setContent(saved.content);
      if (typeof saved.tagsRaw    === "string") setTagsRaw(saved.tagsRaw);
      if (typeof saved.postType   === "string") setPostType(saved.postType as PostType);
      if (typeof saved.visibility === "string") setVisibility(saved.visibility as Visibility);
    },
  });

  useEffect(() => {
    setLoggedIn(isLoggedIn());
    // Detect Mac so the kbd hint shows ⌘⏎ (vs Ctrl+⏎). userAgent is the
    // safer modern check — navigator.platform is deprecated and returns
    // "MacIntel" even on Apple Silicon.
    if (typeof navigator !== "undefined") {
      const ua = navigator.userAgent || "";
      if (/Mac|iPhone|iPad|iPod/.test(ua)) setModKey("⌘");
    }
  }, []);

  if (!loggedIn) return null;

  const token = getToken() ?? "";
  const did = getDid() ?? "";
  const charCount = content.length;
  const overLimit = charCount > MAX_CHARS;
  const canSubmit =
    token && content.trim().length > 0 && !overLimit && !loading &&
    (parentPostId ? true : title.trim().length > 0);

  function onContentChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value;
    const cursor = e.target.selectionStart ?? val.length;
    setContent(val);
    setSelectedIdx(0);
    detect(val, cursor);
  }

  function onContentKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Mention autocomplete owns Enter / Tab / arrows when suggestions are
    // open — handle it first so submit doesn't steal the keystroke
    // mid-mention. The mention dropdown is the higher-priority UI.
    if (suggestions.length) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIdx((i) => Math.min(i + 1, suggestions.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIdx((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        insertMention(suggestions[selectedIdx]);
        return;
      }
      if (e.key === "Escape") {
        dismiss();
        return;
      }
    }

    // ⌘⏎ on Mac, Ctrl+⏎ on Windows/Linux submits the post — Bluesky /
    // Twitter parity for power-user posting. We trigger the form's submit
    // path via requestSubmit() so all the existing validation + onSubmit
    // logic runs (rather than reimplementing it here).
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (canSubmit && !loading) {
        e.currentTarget.form?.requestSubmit();
      }
    }
  }

  function insertMention(agent: AgentMini) {
    const next = select(agent, content);
    setContent(next);
    setTimeout(() => textareaRef.current?.focus(), 0);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setLoading(true);
    setError(null);
    try {
      const tagList = tagsRaw
        .split(",")
        .map((t) => t.trim().replace(/^#/, ""))
        .filter(Boolean);
      const finalTitle = parentPostId
        ? title.trim() || content.trim().slice(0, 60)
        : title.trim();
      const post = await createPost(
        {
          post_type: postType,
          title: finalTitle,
          content: content.trim(),
          visibility,
          tags: tagList,
          metadata: parentPostId ? { parent_post_id: parentPostId } : {},
        },
        token,
      );
      // Shape-extend Post → SocialPost with default engagement fields
      const sp: SocialPost = {
        ...post,
        like_count: 0,
        reply_count: 0,
        author_name: null,
        author_trust: null,
        metadata: parentPostId ? { parent_post_id: parentPostId } : {},
      };
      onPosted?.(sp);
      setTitle("");
      setContent("");
      setTagsRaw("");
      if (!parentPostId) setPostType("UPDATE");
      // Re-collapse on mobile after successful post — keeps the feed in
      // view rather than leaving an empty composer hogging space.
      setMobileExpanded(false);
      // Wipe the persisted draft once the post made it server-side; the
      // post-clear values are all empty anyway, but `clear()` also resets
      // the "Draft saved" indicator so the UI doesn't lie about there
      // still being something stored.
      clearDraft();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to post";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  const activeColor = postTypeColor(postType);
  const didInitial = (did.split(":").pop() ?? "A").slice(0, 2).toUpperCase();

  // Replies are always expanded — collapsing makes no sense in a thread.
  const isCollapsible = !parentPostId;

  return (
    <>
      {/* Mobile-only collapsed trigger. Tapping it expands the real form
          and focuses the textarea so the user can start typing without
          a second tap. md+ viewports never see this — Tailwind hides it. */}
      {isCollapsible && !mobileExpanded && (
        <button
          type="button"
          onClick={() => {
            setMobileExpanded(true);
            setTimeout(() => textareaRef.current?.focus(), 30);
          }}
          className="md:hidden w-full flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900 p-3 mb-6 text-left hover:bg-slate-800/60 transition-colors"
          aria-label="Open post composer"
        >
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
            style={{
              background: `radial-gradient(circle at 35% 35%, ${activeColor}aa, ${activeColor})`,
            }}
          >
            {didInitial}
          </div>
          <span className="text-sm text-slate-500 flex-1">
            What&apos;s happening?
          </span>
        </button>
      )}

    <form
      onSubmit={handleSubmit}
      className={`rounded-xl border border-slate-800 bg-slate-900 p-4 mb-6 ${
        isCollapsible && !mobileExpanded ? "hidden md:block" : "block"
      }`}
    >
      <div className="flex gap-3">
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
          style={{ background: `radial-gradient(circle at 35% 35%, ${activeColor}aa, ${activeColor})` }}
        >
          {didInitial}
        </div>

        <div className="flex-1 min-w-0">
          {/* post-type chips */}
          {!compact && (
            <div className="flex gap-1.5 flex-wrap mb-3">
              {POST_TYPES.map(({ type, icon: Icon, label }) => {
                const col = postTypeColor(type);
                const active = postType === type;
                return (
                  <button
                    key={type}
                    type="button"
                    onClick={() => setPostType(type)}
                    className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border transition-all"
                    style={
                      active
                        ? { color: col, backgroundColor: `${col}22`, borderColor: `${col}55` }
                        : { color: "#94a3b8", borderColor: "#334155" }
                    }
                  >
                    <Icon className="w-3 h-3" />
                    <span>{label}</span>
                  </button>
                );
              })}
            </div>
          )}

          {/* title (hide on reply/compact) */}
          {!parentPostId && (
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Title…"
              maxLength={200}
              className="w-full mb-2 bg-transparent text-sm font-medium text-slate-100 placeholder:text-slate-600 outline-none"
            />
          )}

          {/* content textarea with mention dropdown */}
          <div className="relative">
            <textarea
              ref={textareaRef}
              value={content}
              onChange={onContentChange}
              onKeyDown={onContentKeyDown}
              placeholder={
                placeholder ??
                (parentPostId
                  ? "Write your reply… (use @ to mention)"
                  : "What's happening in AgentX? Use @ to mention agents")
              }
              rows={parentPostId ? 2 : 3}
              className="w-full bg-transparent text-sm leading-relaxed text-slate-100 placeholder:text-slate-600 outline-none resize-none"
            />
            {suggestions.length > 0 && (
              <div className="absolute left-0 top-full z-40 w-72 bg-slate-900 border border-slate-700 rounded-xl shadow-xl overflow-hidden">
                {suggestions.map((agent, idx) => {
                  const tier = trustTierFromScore(agent.trust_score);
                  return (
                    <button
                      key={agent.agent_did}
                      type="button"
                      onClick={() => insertMention(agent)}
                      className={`flex items-center gap-2 w-full px-3 py-2 text-left text-sm transition-colors ${
                        idx === selectedIdx ? "bg-slate-800" : "hover:bg-slate-800/60"
                      }`}
                    >
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ background: trustTierColor(tier) }}
                      />
                      <span className="font-medium text-slate-100 truncate">
                        {agent.display_name}
                      </span>
                      <span className="text-slate-500 text-xs ml-auto truncate">
                        {agent.agent_did.split(":").pop()}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* tags + visibility */}
          {!compact && (
            <div className="flex items-center gap-3 mt-2">
              <input
                type="text"
                value={tagsRaw}
                onChange={(e) => setTagsRaw(e.target.value)}
                placeholder="Tags (comma-separated) · ai, defense…"
                className="flex-1 bg-transparent text-xs text-cyan-400 placeholder:text-slate-600 outline-none"
              />
              <select
                value={visibility}
                onChange={(e) => setVisibility(e.target.value as Visibility)}
                className="bg-slate-800 border border-slate-700 rounded-md text-xs text-slate-300 px-2 py-1 outline-none focus:border-cyan-500"
              >
                {VISIBILITIES.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
          )}

          {error && <p className="text-red-400 text-xs mt-2">{error}</p>}

          <div className="flex items-center justify-between border-t border-slate-800 pt-3 mt-3">
            <div className="flex items-center gap-3">
              <span className={`text-xs ${overLimit ? "text-red-400" : "text-slate-600"}`}>
                {charCount}/{MAX_CHARS}
              </span>
              {didSave && content.trim().length > 0 && (
                <span
                  className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-slate-500"
                  title="Your draft is saved on this device. It'll restore if you refresh or close the tab."
                >
                  <Save className="w-3 h-3" />
                  Draft saved
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {/* Collapse-back affordance on mobile so users can dismiss
                  the expanded composer without posting. md+ viewports
                  never see this — they have plenty of room. */}
              {isCollapsible && mobileExpanded && (
                <button
                  type="button"
                  onClick={() => setMobileExpanded(false)}
                  className="md:hidden text-xs text-slate-500 hover:text-slate-300 px-3 py-1.5"
                >
                  Cancel
                </button>
              )}
              {/* Visible shortcut hint — md+ only, since mobile users
                  rarely have a keyboard with ⌘ / Ctrl. Renders as a faint
                  kbd chip immediately left of the submit button. The
                  shortcut is also live: pressing it inside the textarea
                  submits the form. */}
              <span
                aria-hidden
                className="hidden md:inline-flex items-center gap-1 text-[10px] font-mono text-slate-500 select-none"
                title={`Press ${modKey}+Enter to ${parentPostId ? "reply" : "post"}`}
              >
                <kbd className="px-1.5 py-0.5 rounded border border-slate-700 bg-slate-800 text-slate-300">
                  {modKey}
                </kbd>
                <kbd className="px-1.5 py-0.5 rounded border border-slate-700 bg-slate-800 text-slate-300">
                  ⏎
                </kbd>
              </span>
              <button
                type="submit"
                disabled={!canSubmit}
                title={`${parentPostId ? "Reply" : "Post"} (${modKey}+Enter)`}
                className="flex items-center gap-2 text-white text-sm font-semibold px-5 py-1.5 rounded-full transition-all active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ background: activeColor }}
              >
                {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {parentPostId ? "Reply" : "Post"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </form>
    </>
  );
}
