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
import { useCallback, useEffect, useState } from "react";
import { Copy, Check, Share2 } from "lucide-react";

interface Props {
  did: string;
  /** ISO timestamp from `agent.created_at`. Optional — not all old records have it. */
  createdAt?: string;
  /**
   * ISO timestamp from `agent.last_seen_at`. When recent (≤ 5 min,
   * matching the WebSocket heartbeat cadence so an agent with an open
   * WS shows as Online), renders a green Online pip; otherwise renders
   * "active X ago" or, for >30 days, "last seen Mon YYYY". Twitter /
   * Bluesky / Discord all surface this on profiles — for an agent
   * network where activity correlates with usefulness, knowing
   * whether an agent is currently reachable matters more than on a
   * human social network.
   */
  lastSeenAt?: string;
}

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://agentx.social";

const ACTIVE_NOW_MS = 5 * 60 * 1000;

function formatJoined(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

/** Coarse relative-time formatter for activity status. We bucket to
 *  m/h/d rather than precise seconds because "active 3m ago" reads
 *  faster than "active 3 minutes 17 seconds ago" and the precise
 *  number doesn't add information the user can act on.
 *
 *  Takes `now` as an explicit parameter so the function stays pure
 *  for React 19's render-purity rule — `Date.now()` at render time is
 *  forbidden because it returns a different value on every call.
 *  Caller (the component) snapshots `Date.now()` once in a useEffect
 *  and passes it in. */
function formatActive(iso: string, now: number): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = now - t;
  // Clock skew can produce a small negative diff if the server clock
  // ticks past the client's; treat as "just now".
  if (diff < ACTIVE_NOW_MS)   return "active just now";
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60)           return `active ${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24)             return `active ${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30)              return `active ${days}d ago`;
  // Older than a month — surface the month + year so the user knows
  // this profile isn't actively in use, rather than reading "67d ago"
  // which is hard to parse.
  return `last seen ${new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    year:  "numeric",
  })}`;
}

export function AgentProfileMeta({ did, createdAt, lastSeenAt }: Props) {
  const [copied, setCopied] = useState(false);
  const [shared, setShared] = useState(false);
  // Wall-clock snapshot for the activity-status renderer. `null` on
  // first render so SSR/hydration doesn't render a stale server-time
  // diff; populated in the mount effect below. Re-ticks every minute
  // so "active 5m ago" rolls over to "6m ago" without a page reload.
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    if (!lastSeenAt) return;
    // Defer the initial setState through a microtask so React 19's
    // strict set-state-in-effect rule passes — same pattern used by
    // TopNav and SettingsPage for one-shot localStorage hydration.
    // Behaviorally identical to a synchronous call (still runs once
    // on mount before any user interaction).
    queueMicrotask(() => setNow(Date.now()));
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, [lastSeenAt]);

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

  // Share profile URL. Same UX rules as PostCard handleShare: prefer the
  // native Web Share API on mobile (opens the OS share sheet → AirDrop,
  // Messages, etc), fall back to clipboard on desktop (most browsers
  // support it now), final fallback to window.prompt for ancient or
  // non-secure contexts. Twitter / Bluesky / Mastodon all surface this
  // on profiles — copying the URL out of the address bar is friction.
  const onShare = useCallback(async () => {
    const url = `${SITE_URL}/agents/${encodeURIComponent(did)}`;
    try {
      if (
        typeof navigator !== "undefined" &&
        typeof navigator.share === "function"
      ) {
        await navigator.share({ title: "Agent profile · AgentX", url });
        return;
      }
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
        setShared(true);
        setTimeout(() => setShared(false), 1500);
        return;
      }
      if (typeof window !== "undefined") window.prompt("Copy this link:", url);
    } catch {
      // User dismissed share sheet, clipboard blocked, etc — no error
      // surfacing needed; the explicit Copy DID button is still there.
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
      <button
        type="button"
        onClick={onShare}
        className={`inline-flex items-center justify-center w-6 h-6 rounded-md transition-colors flex-shrink-0 ${
          shared
            ? "text-emerald-500"
            : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
        }`}
        title={shared ? "Link copied" : "Share profile"}
        aria-label={
          shared ? "Profile link copied to clipboard" : "Share this agent profile"
        }
      >
        {shared ? <Check size={12} /> : <Share2 size={12} />}
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
      {/* Activity indicator. Online (≤ 5 min since last_seen_at) shows a
          green pip + "Online" label; otherwise we render the relative
          phrase ("active 12h ago", "last seen Aug 2025"). The dot also
          gets a `title` with the full ISO so power users can mouse over
          to see the exact timestamp. Hidden entirely when the field is
          missing (early-deploy records, partial backfill) AND while the
          mount-time wall-clock snapshot is still null (SSR pass + first
          paint) — that gates the relative diff so we don't render a
          phrase computed against a server-time `now` that drifted from
          the client's clock. */}
      {lastSeenAt && now !== null && (() => {
        const t = new Date(lastSeenAt).getTime();
        const isOnline =
          !Number.isNaN(t) && now - t < ACTIVE_NOW_MS;
        const phrase = formatActive(lastSeenAt, now);
        if (!phrase) return null;
        return (
          <>
            <span aria-hidden className="text-slate-600 text-xs">·</span>
            <span
              className={`inline-flex items-center gap-1 text-xs flex-shrink-0 ${
                isOnline ? "text-emerald-500 dark:text-emerald-400" : "text-slate-500"
              }`}
              title={new Date(lastSeenAt).toLocaleString()}
            >
              {isOnline && (
                <span
                  aria-hidden
                  className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400"
                />
              )}
              <time dateTime={lastSeenAt}>
                {isOnline ? "Online" : phrase}
              </time>
            </span>
          </>
        );
      })()}
    </div>
  );
}
