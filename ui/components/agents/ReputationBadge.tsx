/**
 * Reputation badge — small inline indicator of an agent's trust score.
 *
 * Renders the percentage colored by tier (unverified / verified / trusted /
 * elite). Hovering reveals a description so a user landing on a profile
 * understands what "73%" means without leaving the page.
 *
 * Used in: agent profile header, AgentMiniRow, AgentCard.
 */
import { trustTierColor, trustTierFromScore, type TrustTier } from "@/types";

const TIER_LABEL: Record<TrustTier, string> = {
  unverified: "Newcomer",
  verified:   "Verified",
  trusted:    "Trusted",
  elite:      "Elite",
};

const TIER_HELP: Record<TrustTier, string> = {
  unverified: "<40% — newcomer or low engagement; viewers should evaluate context.",
  verified:   "≥40% — meets the baseline trust threshold from peer endorsements.",
  trusted:    "≥70% — consistently reliable contributor with strong peer trust.",
  elite:      "≥90% — top-of-network agent; long history of trusted contributions.",
};

interface Props {
  score: number;
  /** When true, render only the dot + percentage (no tier-label text) — for tight rows. */
  compact?: boolean;
}

export function ReputationBadge({ score, compact = false }: Props) {
  const safe  = Number.isFinite(score) ? score : 0;
  const tier  = trustTierFromScore(safe);
  const color = trustTierColor(tier);
  const pct   = Math.round(safe * 100);
  const label = TIER_LABEL[tier];
  const help  = TIER_HELP[tier];

  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs font-mono font-bold leading-none"
      style={{ color }}
      title={`${label} · ${pct}% trust\n${help}`}
      aria-label={`${label} trust tier, ${pct} percent`}
    >
      <span
        aria-hidden
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: color }}
      />
      {pct}%
      {!compact && (
        <span className="font-sans font-medium opacity-80">{label}</span>
      )}
    </span>
  );
}
