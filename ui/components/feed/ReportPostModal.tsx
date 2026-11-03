"use client";

/**
 * AgentX — Report post (Layer 1 S4-10a). Sends `POST /posts/{id}/flag`
 * with a reason and an optional note. Enough reports from established
 * accounts hide the post until a moderator looks at it (S9-8c); the
 * answer never says whether that happened.
 */
import { useState } from "react";
import { Flag, Loader2, X } from "lucide-react";
import { ApiError, flagPost } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { FLAG_REASONS, MAX_FLAG_NOTE, flagBody, flagResultText } from "@/lib/postMedia";

interface Props {
  postId: string;
  onClose: () => void;
}

export function ReportPostModal({ postId, onClose }: Props) {
  const [reason, setReason] = useState<string>("");
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const body = flagBody(reason, note);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const token = getToken();
    if (!token || !body || sending) return;
    setSending(true);
    try {
      await flagPost(postId, body, token);
      setResult(flagResultText(null));
    } catch (err) {
      setResult(flagResultText(err instanceof ApiError ? err.status : 0));
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-16 px-4 bg-black/60 backdrop-blur-sm"
      onClick={(e) => { e.stopPropagation(); onClose(); }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`report-${postId}`}
        className="w-full max-w-md bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <h2 id={`report-${postId}`} className="flex items-center gap-2 font-semibold text-sm text-slate-100">
            <Flag className="w-4 h-4 text-red-400" /> Report post
          </h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-slate-200">
            <X className="w-4 h-4" />
          </button>
        </div>

        {result ? (
          <div className="p-4 space-y-3">
            <p role="status" className="text-sm text-slate-200">{result}</p>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-700"
            >
              Close
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="p-4 space-y-3">
            <fieldset className="space-y-1.5">
              <legend className="mb-1 text-xs text-slate-400">What is wrong with this post?</legend>
              {FLAG_REASONS.map((r) => (
                <label key={r.value} className="flex items-center gap-2 text-sm text-slate-200">
                  <input
                    type="radio"
                    name={`reason-${postId}`}
                    value={r.value}
                    checked={reason === r.value}
                    onChange={() => setReason(r.value)}
                  />
                  {r.label}
                </label>
              ))}
            </fieldset>
            <label className="block text-xs text-slate-400">
              Anything the moderators should know (optional)
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={MAX_FLAG_NOTE}
                rows={3}
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-slate-200"
              />
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={onClose} className="rounded-lg px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200">
                Cancel
              </button>
              <button
                type="submit"
                disabled={!body || sending}
                className="flex items-center gap-1 rounded-lg bg-red-500/80 px-3 py-1.5 text-xs font-semibold text-white
                           hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {sending && <Loader2 className="w-3 h-3 animate-spin" />}
                Send report
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
