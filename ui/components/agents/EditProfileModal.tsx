"use client";

/**
 * AgentX — Edit Profile Modal
 * Self-edit overlay for an agent's display_name + bio. Wires to the existing
 * `PATCH /agents/{did}` endpoint via `updateAgent()` in lib/api.ts. Backend
 * authorization (caller.did === target_did) is the boundary; the UI only
 * gates rendering of the entry point.
 *
 * Constraints (mirrored from `AgentUpdate` in platform/src/models/agent.py):
 *   - display_name: 1–64 chars
 *   - bio:          0–512 chars
 */
import { useEffect, useState } from "react";
import { Loader2, X } from "lucide-react";
import { updateAgent } from "@/lib/api";

const MAX_NAME = 64;
const MAX_BIO  = 512;

interface Props {
  did: string;
  initialDisplayName: string;
  initialBio: string;
  token: string;
  onClose: () => void;
  onSaved: (next: { display_name: string; bio: string }) => void;
}

export function EditProfileModal({
  did,
  initialDisplayName,
  initialBio,
  token,
  onClose,
  onSaved,
}: Props) {
  const [displayName, setDisplayName] = useState(initialDisplayName);
  const [bio,         setBio]         = useState(initialBio);
  const [saving,      setSaving]      = useState(false);
  const [error,       setError]       = useState<string | null>(null);

  // Close on Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !saving) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, saving]);

  const trimmedName = displayName.trim();
  const trimmedBio  = bio.trim();
  const nameValid   = trimmedName.length >= 1 && trimmedName.length <= MAX_NAME;
  const bioValid    = trimmedBio.length <= MAX_BIO;
  const dirty =
    trimmedName !== initialDisplayName.trim() ||
    trimmedBio  !== initialBio.trim();
  const canSave = nameValid && bioValid && dirty && !saving;

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const updates: { display_name?: string; bio?: string } = {};
      if (trimmedName !== initialDisplayName.trim()) updates.display_name = trimmedName;
      if (trimmedBio  !== initialBio.trim())         updates.bio          = trimmedBio;
      if (Object.keys(updates).length === 0) {
        onClose();
        return;
      }
      await updateAgent(did, updates, token);
      onSaved({ display_name: trimmedName, bio: trimmedBio });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* backdrop */}
      <button
        type="button"
        onClick={() => !saving && onClose()}
        aria-label="Close"
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
      />

      {/* dialog */}
      <form
        onSubmit={handleSave}
        className="relative w-full max-w-md rounded-xl border border-slate-700 bg-slate-900 shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label="Edit profile"
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-slate-100">Edit profile</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="text-slate-500 hover:text-slate-200 transition-colors disabled:opacity-50"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* display_name */}
          <label className="block">
            <span className="text-xs text-slate-400 mb-1 block">Display name</span>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value.slice(0, MAX_NAME))}
              maxLength={MAX_NAME}
              autoFocus
              className="w-full bg-slate-800 border border-slate-700 rounded-md px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-500"
              placeholder="Your name"
            />
            <span className={`block text-[10px] mt-1 ${nameValid ? "text-slate-600" : "text-red-400"}`}>
              {trimmedName.length}/{MAX_NAME}
              {!nameValid && trimmedName.length === 0 && " — required"}
            </span>
          </label>

          {/* bio */}
          <label className="block">
            <span className="text-xs text-slate-400 mb-1 block">Bio</span>
            <textarea
              value={bio}
              onChange={(e) => setBio(e.target.value.slice(0, MAX_BIO))}
              maxLength={MAX_BIO}
              rows={4}
              className="w-full bg-slate-800 border border-slate-700 rounded-md px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-500 resize-none"
              placeholder="A short description of yourself or your agent"
            />
            <span className={`block text-[10px] mt-1 ${bioValid ? "text-slate-600" : "text-red-400"}`}>
              {trimmedBio.length}/{MAX_BIO}
            </span>
          </label>

          {error && (
            <p className="text-xs text-red-400">{error}</p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-slate-800">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!canSave}
            className="flex items-center gap-2 px-4 py-1.5 rounded-full bg-cyan-600 text-white text-sm font-semibold hover:bg-cyan-500 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Save
          </button>
        </div>
      </form>
    </div>
  );
}
