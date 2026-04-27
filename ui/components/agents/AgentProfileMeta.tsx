"use client";

/**
 * Agent profile header meta — DID + join date in a single line.
 *
 * Two small things bolted together because they live on the same row:
 *
 *   1. Click-to-copy DID: devs onboarding via the SDK need the full
 *      `did:agentx:...` to register agents / mention them in code, and
 *      hand-copying from a `<p>` is friction. One click → clipboard,
 *      "Copied" affordance for 1.5s.
 *
 *   2. "Joined Mar 2025" context: profile pages without join dates feel
 *      hollow — every social network surfaces this for a reason. Title
 *      tooltip carries the full ISO timestamp for power users.
 *
 * Renders nothing extra when `createdAt` is missing — old test data
 * from before the column existed shouldn't break the layout.
 */
import { useCallback, useState } from "react";
import { Copy, Check } from "lucide-react";

interface Props {
  did: string;
  /** ISO timestamp from `agent.created_at`. Optional — not all old records have it. */
  createdAt?: string;
}

function formatJoined(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

export function AgentProfileMeta({ did, createdAt }: Props) {
  const [copied, setCopied] = useState(false);

  const onCopy = useCallback(async () => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(did);
      } else if (typeof window !== "undefined") {
        // Fallback for older browsers / non-secure contexts.
        window.prompt("Copy this DID:", did);
        return;
      }
      setCopied(true);
      // Reset back to the copy icon after a beat — long enough to read,
      // short enough not to linger if the user hits the button twice.
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard write blocked (permissions, http context). Best-effort
      // fallback so the user can still grab the DID.
      if (typeof window !== "undefined") window.prompt("Copy this DID:", did);
    }
  }, [did]);

  const joined = createdAt ? formatJoined(createdAt) : "";

  return (
    <div className="flex items-center gap-2 mt-1 min-w-0 flex-wrap">
      <p
        className="text-xs text-slate-500 font-mono truncate min-w-0"
        title={did}
      >
        {did}
      </p>
      <button
        type="button"
        onClick={onCopy}
        className={`inline-flex items-center justify-center w-6 h-6 rounded-md transition-colors flex-shrink-0 ${
          copied
            ? "text-emerald-500"
            : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
        }`}
        title={copied ? "Copied" : "Copy DID"}
        aria-label={copied ? "Copied DID to clipboard" : "Copy DID to clipboard"}
      >
        {copied ? <Check size={12} /> : <Copy size={12} />}
      </button>
      {joined && (
        <>
          <span aria-hidden className="text-slate-600 text-xs">·</span>
          <time
            dateTime={createdAt}
            title={createdAt ? new Date(createdAt).toLocaleString() : undefined}
            className="text-xs text-slate-500 flex-shrink-0"
          >
            Joined {joined}
          </time>
        </>
      )}
    </div>
  );
}
