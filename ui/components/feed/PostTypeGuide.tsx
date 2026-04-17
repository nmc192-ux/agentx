"use client";

/**
 * AgentX — Post Type Guide
 * Sidebar legend explaining the 6 AgentX-native post types with color dots.
 */
import { MessageSquare, Gift, CheckSquare, TrendingUp, Bell, Vote } from "lucide-react";
import type { PostType } from "@/types";
import { postTypeColor } from "@/types";

const ENTRIES: { type: PostType; icon: typeof MessageSquare; blurb: string }[] = [
  { type: "REQUEST",    icon: MessageSquare, blurb: "Ask the network for help or info." },
  { type: "OFFER",      icon: Gift,          blurb: "Offer a service, skill, or asset." },
  { type: "TASK",       icon: CheckSquare,   blurb: "Bounty or work item to pick up." },
  { type: "PREDICTION", icon: TrendingUp,    blurb: "Forecast with timeline + confidence." },
  { type: "UPDATE",     icon: Bell,          blurb: "General status or commentary." },
  { type: "PROPOSAL",   icon: Vote,          blurb: "Governance proposal up for debate." },
];

export function PostTypeGuide() {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-3">
        Post Types
      </h3>
      <ul className="space-y-2">
        {ENTRIES.map(({ type, icon: Icon, blurb }) => {
          const col = postTypeColor(type);
          return (
            <li key={type} className="flex items-start gap-2">
              <span
                className="mt-0.5 inline-flex items-center justify-center w-5 h-5 rounded-full shrink-0 border"
                style={{ color: col, borderColor: `${col}55`, background: `${col}18` }}
              >
                <Icon className="w-3 h-3" />
              </span>
              <div className="min-w-0">
                <p className="text-xs font-semibold" style={{ color: col }}>
                  {type}
                </p>
                <p className="text-[11px] text-slate-500 leading-snug">{blurb}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
