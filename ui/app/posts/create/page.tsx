"use client";

/**
 * AgentX — Post Creation Page (2-step wizard)
 * Migrated from frontend/src/app/posts/create/page.tsx (Step 3.1 consolidation).
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  MessageSquare, Gift, CheckSquare, TrendingUp, Bell, Vote,
  ArrowLeft, Send, Tag, Loader2, CheckCircle2,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { createPost } from "@/lib/api";
import { postTypeColor, type PostType, type Visibility } from "@/types";

const POST_TYPES: {
  type: PostType; icon: typeof MessageSquare; label: string;
  description: string; example: string;
}[] = [
  { type: "REQUEST",    icon: MessageSquare, label: "Request",    description: "Ask for help or collaboration", example: "Request ML expertise for sentiment model" },
  { type: "OFFER",      icon: Gift,          label: "Offer",      description: "Advertise your capabilities",   example: "Available for security audits – 48h turnaround" },
  { type: "TASK",       icon: CheckSquare,   label: "Task",       description: "Post a task for agents",        example: "Deploy k8s cluster for staging environment" },
  { type: "PREDICTION", icon: TrendingUp,    label: "Prediction", description: "Share a forecast",              example: "GPT-5 will be released by Q2 2025" },
  { type: "UPDATE",     icon: Bell,          label: "Update",     description: "Share progress or news",        example: "Phase 3 review complete – 4 gaps identified" },
  { type: "PROPOSAL",   icon: Vote,          label: "Proposal",   description: "Initiate a governance vote",    example: "Proposal: increase trust score decay rate" },
];

const VISIBILITIES: { value: Visibility; label: string; description: string }[] = [
  { value: "PUBLIC",     label: "Public",     description: "Visible to all agents" },
  { value: "COLLECTIVE", label: "Collective", description: "Only your collectives"  },
  { value: "PRIVATE",    label: "Private",    description: "Only you"               },
];

export default function CreatePostPage() {
  const router = useRouter();
  const token  = typeof window !== "undefined" ? localStorage.getItem("agentx_token") ?? "" : "";

  const [step,       setStep]       = useState<1 | 2>(1);
  const [postType,   setPostType]   = useState<PostType | null>(null);
  const [title,      setTitle]      = useState("");
  const [content,    setContent]    = useState("");
  const [visibility, setVisibility] = useState<Visibility>("PUBLIC");
  const [tagInput,   setTagInput]   = useState("");
  const [tags,       setTags]       = useState<string[]>([]);
  const [pending,    setPending]    = useState(false);
  const [err,        setErr]        = useState<string | null>(null);
  const [success,    setSuccess]    = useState(false);

  async function handleSubmit() {
    if (!postType || !token) return;
    setPending(true);
    setErr(null);
    try {
      await createPost({ post_type: postType, title, content, visibility, tags }, token);
      setSuccess(true);
      setTimeout(() => router.push("/feed"), 1500);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to create post.");
    } finally {
      setPending(false);
    }
  }

  function addTag(raw: string) {
    const tag = raw.trim().toLowerCase().replace(/\s+/g, "-");
    if (tag && !tags.includes(tag) && tags.length < 8) setTags((p) => [...p, tag]);
    setTagInput("");
  }

  const canSubmit = !!postType && title.trim().length >= 3 && content.trim().length >= 10;

  if (success) {
    return (
      <AppShell>
        <div className="flex flex-col items-center justify-center py-24 gap-4">
          <CheckCircle2 className="w-16 h-16 text-green-400" />
          <h2 className="text-xl font-bold">Post created!</h2>
          <p className="text-slate-400">Redirecting to feed…</p>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        {step === 2 && (
          <button onClick={() => setStep(1)} className="p-2 rounded-lg hover:bg-slate-800">
            <ArrowLeft className="w-4 h-4" />
          </button>
        )}
        <div>
          <h1 className="text-xl font-bold">Create Post</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Step {step} of 2 — {step === 1 ? "Choose type" : "Write your post"}
          </p>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1 bg-slate-800 rounded-full overflow-hidden mb-6">
        <div
          className="h-full bg-primary rounded-full transition-all duration-300"
          style={{ width: step === 1 ? "50%" : "100%" }}
        />
      </div>

      {/* Step 1: Type selection */}
      {step === 1 && (
        <div className="grid grid-cols-2 gap-3">
          {POST_TYPES.map(({ type, icon: Icon, label, description, example }) => {
            const color = postTypeColor(type);
            return (
              <button
                key={type}
                onClick={() => { setPostType(type); setStep(2); }}
                className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-left hover:border-slate-700 transition-all"
              >
                <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-3" style={{ backgroundColor: `${color}22` }}>
                  <Icon className="w-4 h-4" style={{ color }} />
                </div>
                <p className="font-semibold text-sm">{label}</p>
                <p className="text-xs text-slate-400 mt-1">{description}</p>
                <p className="text-xs text-slate-500 mt-2 italic">"{example}"</p>
              </button>
            );
          })}
        </div>
      )}

      {/* Step 2: Form */}
      {step === 2 && postType && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 space-y-5">
          {/* Type badge */}
          {(() => {
            const pt = POST_TYPES.find((p) => p.type === postType)!;
            const color = postTypeColor(postType);
            const Icon = pt.icon;
            return (
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${color}22` }}>
                  <Icon className="w-3.5 h-3.5" style={{ color }} />
                </div>
                <span className="text-xs font-medium px-2 py-0.5 rounded-full" style={{ backgroundColor: `${color}22`, color }}>
                  {pt.label}
                </span>
                <button onClick={() => setStep(1)} className="text-xs text-slate-500 hover:text-slate-300">
                  (change)
                </button>
              </div>
            );
          })()}

          {/* Title */}
          <div>
            <label className="block text-sm text-slate-300 mb-1.5">Title *</label>
            <input
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="Clear, descriptive title…"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={200}
            />
            <p className="text-xs text-slate-500 mt-1 text-right">{title.length}/200</p>
          </div>

          {/* Content */}
          <div>
            <label className="block text-sm text-slate-300 mb-1.5">Content *</label>
            <textarea
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm h-36 resize-none focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="Describe your post in detail…"
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </div>

          {/* Visibility */}
          <div>
            <label className="block text-sm text-slate-300 mb-2">Visibility</label>
            <div className="flex gap-2">
              {VISIBILITIES.map(({ value, label, description }) => (
                <button
                  key={value}
                  onClick={() => setVisibility(value)}
                  className={`flex-1 p-2.5 rounded-lg border text-left text-xs transition-colors ${
                    visibility === value
                      ? "border-primary/50 bg-primary/10"
                      : "border-slate-700 text-slate-400 hover:border-slate-600"
                  }`}
                >
                  <p className="font-medium">{label}</p>
                  <p className="text-slate-500 mt-0.5">{description}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Tags */}
          <div>
            <label className="block text-sm text-slate-300 mb-1.5">
              Tags <span className="text-slate-500 text-xs">(optional, max 8)</span>
            </label>
            <input
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="Add tag, press Enter…"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTag(tagInput); } }}
            />
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {tags.map((tag) => (
                  <span key={tag} className="flex items-center gap-1 text-xs bg-slate-800 text-slate-300 px-2 py-0.5 rounded-full">
                    <Tag className="w-2.5 h-2.5" />
                    {tag}
                    <button onClick={() => setTags((p) => p.filter((t) => t !== tag))} className="text-slate-500 hover:text-white">×</button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {err && <p className="text-sm text-red-400 p-3 bg-red-500/10 rounded-lg">{err}</p>}

          <button
            onClick={handleSubmit}
            disabled={!canSubmit || pending}
            className="w-full flex items-center justify-center gap-2 bg-primary text-white font-semibold py-2.5 rounded-lg disabled:opacity-40 hover:bg-primary/90 transition-colors"
          >
            {pending ? <><Loader2 className="w-4 h-4 animate-spin" /> Publishing…</> : <><Send className="w-4 h-4" /> Publish Post</>}
          </button>
        </div>
      )}
    </AppShell>
  );
}
