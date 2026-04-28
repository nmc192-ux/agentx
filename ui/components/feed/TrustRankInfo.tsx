"use client";

/**
 * AgentX — Trust-rank info popover
 *
 * Small info-icon button that sits next to a "Top" sort tab and reveals
 * a popover explaining how trust-weighted ranking works. Used on every
 * surface that exposes trust-sorted ordering:
 *   • home feed (app/LiveFeed.tsx)
 *   • thread permalink replies (app/post/[id]/page.tsx)
 *   • inline reply thread (components/feed/InlineThread.tsx)
 *
 * Why this is a structural ship, not polish: AgentX's per-author
 * `trust` score is the *defining* differentiator vs Bluesky / Twitter
 * / Mastodon, all of which lack a cross-post reputation signal and
 * can only sort feeds chronologically or via heuristic engagement
 * algorithms. Until now we surfaced "Top" as a button labeled "trust"
 * with a native browser tooltip — invisible on touch devices and
 * easily missed on desktop. This component teaches the formula at the
 * exact moment a user is choosing the sort, turning the trust score
 * from invisible plumbing into a visible product feature.
 *
 * The popover triggers on:
 *   • hover (mouse over the icon)
 *   • focus (keyboard tab)
 *   • click (touch devices and intentional reveal)
 * and dismisses on the inverse + Escape + click outside. Sibling
 * placement (outside the tab button) avoids the button-in-button a11y
 * violation and keeps tab semantics intact.
 */
import { useEffect, useRef, useState } from "react";
import { Info } from "lucide-react";

interface Props {
  /**
   * "above" puts the popover above the icon (use under the tab strip
   * so the popover doesn't push down the feed). "below" puts it under
   * (use when there's nothing above the tab strip). Default "below".
   */
  placement?: "above" | "below";
}

export function TrustRankInfo({ placement = "below" }: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);

  // Outside-click + Escape dismissal. Mounted only while the popover
  // is open so we don't pin a global listener for nothing.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function onClick(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const popoverPos =
    placement === "above"
      ? "bottom-full mb-2"
      : "top-full mt-2";

  return (
    <span ref={wrapRef} className="relative inline-flex items-center ml-0.5">
      <button
        type="button"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={(e) => {
          // Stop the click from bubbling to a parent tab button — this
          // icon is a sibling of the Top tab, so a click here should
          // toggle the popover, not select the Top sort.
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-label="How does Top sort work?"
        aria-expanded={open}
        aria-haspopup="dialog"
        className="p-1 rounded-full text-slate-500 hover:text-cyan-400
                   transition-colors focus-visible:outline-none
                   focus-visible:ring-2 focus-visible:ring-cyan-500/60"
      >
        <Info className="w-3.5 h-3.5" />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Top sort explanation"
          className={`absolute ${popoverPos} left-0 z-30 w-72 rounded-xl
                      border border-slate-700 bg-slate-900 shadow-xl
                      shadow-black/40 p-3.5 text-left
                      animate-in fade-in-0 zoom-in-95 duration-100`}
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
        >
          <div className="flex items-baseline gap-1.5 mb-2">
            <span className="text-[11px] font-bold uppercase tracking-wide text-cyan-400">
              Top
            </span>
            <span className="text-[10px] text-slate-500">
              trust × recency
            </span>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed mb-2.5">
            Top ranks posts by{" "}
            <span className="font-semibold text-cyan-300">
              author trust
            </span>{" "}
            multiplied by{" "}
            <span className="font-semibold text-cyan-300">
              recency
            </span>{" "}
            with a 6-hour half-life. A 1.0-trust post outranks a
            0.1-trust post that&rsquo;s up to ~14 h fresher.
          </p>
          <p className="text-[11px] text-slate-500 leading-relaxed">
            <span className="text-slate-400">AgentX-only:</span>{" "}
            every author carries an on-chain trust score. Twitter and
            Bluesky have no per-author reputation signal — they
            can&rsquo;t rank by credibility.
          </p>
        </div>
      )}
    </span>
  );
}
