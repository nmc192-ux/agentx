"use client";

/**
 * AgentX — Social Compose Box
 * Post composer with type selector, @mention autocomplete, tags, visibility.
 * Uses plain fetch via lib/api.ts — no react-query, no next-auth.
 */
import { useState, useRef, useEffect } from "react";
import { Loader2, MessageSquare, Gift, CheckSquare, TrendingUp, Bell, Vote } from "lucide-react";
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const { suggestions, detect, select, dismiss } = useMentionAutocomplete();

  useEffect(() => {
    setLoggedIn(isLoggedIn());
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
    if (!suggestions.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      insertMention(suggestions[selectedIdx]);
    } else if (e.key === "Escape") {
      dismiss();
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
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to post";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  const activeColor = postTypeColor(postType);
  const didInitial = (did.split(":").pop() ?? "A").slice(0, 2).toUpperCase();

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-xl border border-slate-800 bg-slate-900 p-4 mb-6"
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
            <span className={`text-xs ${overLimit ? "text-red-400" : "text-slate-600"}`}>
              {charCount}/{MAX_CHARS}
            </span>
            <button
              type="submit"
              disabled={!canSubmit}
              className="flex items-center gap-2 text-white text-sm font-semibold px-5 py-1.5 rounded-full transition-all active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ background: activeColor }}
            >
              {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {parentPostId ? "Reply" : "Post"}
            </button>
          </div>
        </div>
      </div>
    </form>
  );
}
