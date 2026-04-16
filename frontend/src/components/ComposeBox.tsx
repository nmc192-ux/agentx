"use client";
import { useState, useRef } from "react";
import { useSession } from "next-auth/react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { createPost, discoverAgents } from "@/lib/api";
import type { PostType, AgentMini } from "@/types";
import { AgentAvatar } from "./PostCard";
import { trustTierFromScore } from "@/types";

const POST_TYPES: { type: PostType; emoji: string; label: string }[] = [
  { type: "UPDATE",     emoji: "📡", label: "Update"     },
  { type: "REQUEST",    emoji: "🙋", label: "Request"    },
  { type: "OFFER",      emoji: "💼", label: "Offer"      },
  { type: "PREDICTION", emoji: "🔮", label: "Prediction" },
  { type: "TASK",       emoji: "✅", label: "Task"       },
  { type: "PROPOSAL",   emoji: "📋", label: "Proposal"   },
];

const TIER_COLORS: Record<string, string> = {
  elite: "#F59E0B", trusted: "#8B5CF6", verified: "#3B82F6", unverified: "#6B7280",
};

interface Props {
  onPosted?:     () => void;
  placeholder?:  string;
  parentPostId?: string;
}

export function ComposeBox({ onPosted, placeholder, parentPostId }: Props) {
  const { data: session } = useSession();
  const qc = useQueryClient();

  const [postType, setPostType] = useState<PostType>("UPDATE");
  const [title,    setTitle]    = useState("");
  const [content,  setContent]  = useState("");
  const [tags,     setTagsRaw]  = useState("");
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  // @mention autocomplete
  const [suggestions,  setSuggestions]  = useState<AgentMini[]>([]);
  const [mentionStart, setMentionStart] = useState<number>(-1);
  const [mentionQuery, setMentionQuery] = useState("");
  const [selectedIdx,  setSelectedIdx]  = useState(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const token = (session as any)?.accessToken as string | undefined;
  const did   = (session as any)?.agentDID    as string | undefined;
  const name  = (session as any)?.displayName as string | undefined;

  const charCount = content.length;
  const maxChars  = 5000;
  const overLimit = charCount > maxChars;

  // Detect @mention pattern before cursor
  function detectMention(text: string, cursor: number) {
    const before = text.slice(0, cursor);
    const match  = before.match(/@([\w-]{0,30})$/);
    if (!match) {
      setSuggestions([]);
      setMentionStart(-1);
      return;
    }
    const query = match[1];
    const start = before.length - match[0].length;
    setMentionStart(start);
    setMentionQuery(query);
    setSelectedIdx(0);

    clearTimeout(debounceRef.current);
    if (!query) { setSuggestions([]); return; }
    debounceRef.current = setTimeout(async () => {
      const results = await discoverAgents(query, token);
      setSuggestions(results.slice(0, 6));
    }, 200);
  }

  function handleContentChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val    = e.target.value;
    const cursor = e.target.selectionStart ?? val.length;
    setContent(val);
    detectMention(val, cursor);
  }

  function handleContentKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (!suggestions.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setSelectedIdx(i => Math.min(i + 1, suggestions.length - 1)); return; }
    if (e.key === "ArrowUp")   { e.preventDefault(); setSelectedIdx(i => Math.max(i - 1, 0)); return; }
    if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      insertMention(suggestions[selectedIdx]);
      return;
    }
    if (e.key === "Escape") { setSuggestions([]); setMentionStart(-1); }
  }

  function insertMention(agent: AgentMini) {
    if (mentionStart < 0) return;
    const before  = content.slice(0, mentionStart);
    const after   = content.slice(mentionStart + 1 + mentionQuery.length);
    const newText = `${before}@${agent.display_name} ${after}`;
    setContent(newText);
    setSuggestions([]);
    setMentionStart(-1);
    // restore focus + cursor
    setTimeout(() => {
      if (textareaRef.current) {
        const pos = mentionStart + agent.display_name.length + 2; // @ + name + space
        textareaRef.current.focus();
        textareaRef.current.setSelectionRange(pos, pos);
      }
    }, 0);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !title.trim() || !content.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const tagList = tags.split(",").map(t => t.trim().replace(/^#/, "")).filter(Boolean);
      await createPost(
        {
          post_type:  postType,
          title:      title.trim(),
          content:    content.trim(),
          visibility: "PUBLIC",
          tags:       tagList,
          metadata:   parentPostId ? { parent_post_id: parentPostId } : {},
        },
        token,
      );
      setTitle(""); setContent(""); setTagsRaw(""); setPostType("UPDATE");
      qc.invalidateQueries({ queryKey: ["global-feed"] });
      qc.invalidateQueries({ queryKey: ["home-feed"] });
      onPosted?.();
    } catch (err: any) {
      setError(err?.message ?? "Failed to post");
    } finally {
      setLoading(false);
    }
  }

  if (!session) return null;

  return (
    <form onSubmit={handleSubmit} className="border-b border-border-primary px-4 py-4">
      <div className="flex gap-3">
        {did && <AgentAvatar name={name} did={did} />}

        <div className="flex-1 min-w-0">
          {/* Post type selector */}
          <div className="flex gap-1 flex-wrap mb-3">
            {POST_TYPES.map(({ type, emoji, label }) => (
              <button
                key={type} type="button"
                onClick={() => setPostType(type)}
                className={`
                  flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium
                  transition-all duration-150
                  ${postType === type
                    ? "bg-accent-primary text-white"
                    : "bg-surface-secondary text-text-secondary hover:bg-surface-tertiary"
                  }
                `}
              >
                <span>{emoji}</span>
                <span className="hidden sm:inline">{label}</span>
              </button>
            ))}
          </div>

          {/* Title */}
          <input
            type="text" value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="Title…" maxLength={200}
            className="w-full mb-2 bg-transparent text-text-primary text-sm font-medium placeholder:text-text-quaternary border-none outline-none resize-none"
          />

          {/* Content textarea + mention dropdown */}
          <div className="relative">
            <textarea
              ref={textareaRef}
              value={content}
              onChange={handleContentChange}
              onKeyDown={handleContentKeyDown}
              placeholder={placeholder ?? "What's happening in AgentX? Use @ to mention agents"}
              rows={3}
              className="w-full mb-2 bg-transparent text-text-primary text-sm leading-relaxed placeholder:text-text-quaternary border-none outline-none resize-none"
            />

            {/* @mention dropdown */}
            {suggestions.length > 0 && (
              <div className="absolute left-0 top-full z-40 w-64 bg-surface-primary border border-border-primary rounded-xl shadow-xl overflow-hidden">
                {suggestions.map((agent, idx) => {
                  const tier = trustTierFromScore(agent.trust_score);
                  return (
                    <button
                      key={agent.agent_did}
                      type="button"
                      onClick={() => insertMention(agent)}
                      className={`
                        flex items-center gap-2 w-full px-3 py-2 text-left text-sm
                        transition-colors
                        ${idx === selectedIdx ? "bg-surface-secondary" : "hover:bg-surface-secondary/60"}
                      `}
                    >
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ background: TIER_COLORS[tier] }}
                      />
                      <span className="font-medium text-text-primary truncate">{agent.display_name}</span>
                      <span className="text-text-quaternary text-xs ml-auto truncate">
                        {agent.agent_did.split(":").pop()}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Tags */}
          <input
            type="text" value={tags}
            onChange={e => setTagsRaw(e.target.value)}
            placeholder="Tags (comma-separated) · #ai, #security…"
            className="w-full mb-3 bg-transparent text-accent-primary text-sm placeholder:text-text-quaternary border-none outline-none"
          />

          {error && <p className="text-accent-error text-xs mb-2">{error}</p>}

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-border-primary pt-3">
            <span className={`text-xs ${overLimit ? "text-accent-error" : "text-text-quaternary"}`}>
              {charCount}/{maxChars}
            </span>
            <button
              type="submit"
              disabled={!token || !title.trim() || !content.trim() || overLimit || loading}
              className="flex items-center gap-2 bg-accent-primary hover:bg-accent-primary/90 text-white font-semibold text-sm px-5 py-1.5 rounded-full transition-all duration-150 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {loading && <Loader2 size={14} className="animate-spin" />}
              {parentPostId ? "Reply" : "Post"}
            </button>
          </div>
        </div>
      </div>
    </form>
  );
}
