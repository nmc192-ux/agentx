"use client";

/**
 * ArtifactModal — Create or view an artifact.
 *
 * CREATE mode: type selector, title, content editor (JSON or plain text)
 * VIEW mode: renders artifact content with syntax highlighting for CODE,
 *            formatted JSON for others.
 *
 * Also places a canvas node when creating an artifact with artifact_id linked.
 */
import { useState } from "react";
import { motion } from "framer-motion";
import {
  X, FileText, Code, FileImage, ScrollText, GitBranch, BookOpen,
  Loader2,
} from "lucide-react";
import { addArtifact, createCanvasNode } from "@/lib/api";
import type { Artifact, ArtifactType } from "@/types";

const TYPES: { value: ArtifactType; label: string; icon: typeof FileText; color: string }[] = [
  { value: "NOTE",        label: "Note",        icon: FileText,  color: "#3b82f6" },
  { value: "CODE",        label: "Code",        icon: Code,       color: "#a855f7" },
  { value: "DIAGRAM",     label: "Diagram",     icon: FileImage,  color: "#06b6d4" },
  { value: "LOG",         label: "Log",         icon: ScrollText, color: "#22c55e" },
  { value: "WORKFLOW",    label: "Workflow",     icon: GitBranch,  color: "#f59e0b" },
  { value: "RAG_SNIPPET", label: "RAG Snippet", icon: BookOpen,   color: "#ef4444" },
];

interface Props {
  roomId: string;
  artifact: Artifact | null;      // null = create mode, non-null = view mode
  token: string;
  onClose: () => void;
  onCreated: () => void;
}

export function ArtifactModal({ roomId, artifact, token, onClose, onCreated }: Props) {
  const isView = artifact !== null;

  // Create form state
  const [artType, setArtType] = useState<ArtifactType>("NOTE");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate() {
    if (!title.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      // Build content — CODE gets source field, others get text
      let content: Record<string, unknown>;
      if (artType === "CODE") {
        content = { source: body, language: "python" };
      } else if (artType === "LOG") {
        content = { entries: body.split("\n").filter(Boolean) };
      } else {
        content = { text: body };
      }

      const newArt = await addArtifact(roomId, {
        artifact_type: artType,
        title,
        content,
      }, token);

      // Auto-place canvas node for this artifact
      const nodeX = 100 + Math.random() * 400;
      const nodeY = 80 + Math.random() * 300;
      await createCanvasNode(roomId, {
        artifact_id: newArt.artifact_id,
        node_type: "artifact",
        label: title,
        x: nodeX,
        y: nodeY,
      }, token).catch(() => {});  // non-critical if canvas node fails

      onCreated();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create artifact");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0, y: 10 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.95, opacity: 0, y: 10 }}
        transition={{ type: "spring", damping: 25, stiffness: 300 }}
        className="w-full max-w-lg mx-4 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-slate-200">
            {isView ? "View Artifact" : "New Artifact"}
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4 max-h-[70vh] overflow-y-auto">
          {isView ? (
            <ViewContent artifact={artifact} />
          ) : (
            <>
              {/* Type selector */}
              <div>
                <label className="text-xs text-slate-400 mb-1.5 block">Type</label>
                <div className="flex flex-wrap gap-2">
                  {TYPES.map((t) => {
                    const Icon = t.icon;
                    return (
                      <button
                        key={t.value}
                        onClick={() => setArtType(t.value)}
                        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all"
                        style={
                          artType === t.value
                            ? { borderColor: `${t.color}88`, color: t.color, backgroundColor: `${t.color}12` }
                            : { borderColor: "#334155", color: "#94a3b8" }
                        }
                      >
                        <Icon className="w-3 h-3" /> {t.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Title */}
              <div>
                <label className="text-xs text-slate-400 mb-1.5 block">Title</label>
                <input
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                  placeholder="Artifact title..."
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  autoFocus
                />
              </div>

              {/* Content */}
              <div>
                <label className="text-xs text-slate-400 mb-1.5 block">
                  {artType === "CODE" ? "Source Code" : artType === "LOG" ? "Log Entries (one per line)" : "Content"}
                </label>
                <textarea
                  className={`w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500 resize-none ${
                    artType === "CODE" ? "font-mono text-xs" : ""
                  }`}
                  rows={8}
                  placeholder={
                    artType === "CODE" ? "def main():\n    pass" :
                    artType === "LOG" ? "2026-04-15 10:00:00 - Agent started\n..." :
                    "Write your content here..."
                  }
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                />
              </div>

              {error && (
                <p className="text-xs text-red-400">{error}</p>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {!isView && (
          <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-slate-800">
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={submitting || !title.trim()}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-cyan-600 text-white text-xs font-medium hover:bg-cyan-500 disabled:opacity-50 transition-colors"
            >
              {submitting ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
              Create & Place on Canvas
            </button>
          </div>
        )}
      </motion.div>
    </motion.div>
  );
}

// ── View mode ───────────────────────────────────────────────────────────────

function ViewContent({ artifact }: { artifact: Artifact }) {
  const typeDef = TYPES.find((t) => t.value === artifact.artifact_type);
  const Icon = typeDef?.icon ?? FileText;
  const color = typeDef?.color ?? "#3b82f6";
  const content = artifact.content;

  return (
    <div className="space-y-3">
      {/* Type + title */}
      <div className="flex items-center gap-2">
        <div className="p-1.5 rounded-lg" style={{ backgroundColor: `${color}18` }}>
          <Icon className="w-4 h-4" style={{ color }} />
        </div>
        <div>
          <h3 className="font-semibold text-sm text-slate-200">{artifact.title || "Untitled"}</h3>
          <span className="text-[10px] text-slate-500">
            {artifact.artifact_type} &middot; by {artifact.author_did.split(":").pop()} &middot; {new Date(artifact.created_at).toLocaleString()}
          </span>
        </div>
      </div>

      {/* Content render */}
      {artifact.artifact_type === "CODE" && typeof content.source === "string" ? (
        <pre className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs font-mono text-green-300 overflow-x-auto whitespace-pre-wrap">
          {content.source}
        </pre>
      ) : artifact.artifact_type === "LOG" && Array.isArray(content.entries) ? (
        <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs font-mono space-y-0.5 max-h-64 overflow-y-auto">
          {(content.entries as string[]).map((line, i) => (
            <div key={i} className="text-slate-400">
              <span className="text-slate-600 mr-2 select-none">{String(i + 1).padStart(3, " ")}</span>
              {line}
            </div>
          ))}
        </div>
      ) : typeof content.text === "string" ? (
        <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-sm text-slate-300 whitespace-pre-wrap">
          {content.text}
        </div>
      ) : (
        <pre className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs font-mono text-slate-400 overflow-x-auto">
          {JSON.stringify(content, null, 2)}
        </pre>
      )}
    </div>
  );
}
