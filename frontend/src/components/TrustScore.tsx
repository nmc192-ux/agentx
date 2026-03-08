"use client";

/**
 * AgentX — TrustScore display component
 * Shows the numeric trust score with tier color, ring progress, and breakdown.
 */
import { motion } from "framer-motion";
import { Shield, TrendingUp } from "lucide-react";
import { cn, formatTrust } from "@/lib/utils";
import { trustTierFromScore, trustTierColor, type TrustTier } from "@/types";

interface TrustScoreProps {
  score:      number;       // 0.0 – 1.0
  size?:      "sm" | "md" | "lg";
  showTier?:  boolean;
  showLabel?: boolean;
  className?: string;
}

const SIZE_CLASSES = {
  sm: { ring: "w-10 h-10", text: "text-xs",  icon: "w-3.5 h-3.5" },
  md: { ring: "w-14 h-14", text: "text-sm",  icon: "w-4 h-4"     },
  lg: { ring: "w-20 h-20", text: "text-lg",  icon: "w-5 h-5"     },
};

const TIER_LABELS: Record<TrustTier, string> = {
  unverified: "Unverified",
  verified:   "Verified",
  trusted:    "Trusted",
  elite:      "Elite",
};

export function TrustScore({
  score,
  size       = "md",
  showTier   = true,
  showLabel  = false,
  className,
}: TrustScoreProps) {
  const tier  = trustTierFromScore(score);
  const color = trustTierColor(tier);
  const pct   = Math.round(score * 100);
  const sz    = SIZE_CLASSES[size];

  // SVG ring
  const radius     = 20;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (pct / 100) * circumference;

  return (
    <div className={cn("flex items-center gap-3", className)}>
      {/* Ring */}
      <div className={cn("relative shrink-0", sz.ring)}>
        <svg viewBox="0 0 50 50" className="w-full h-full -rotate-90">
          {/* Track */}
          <circle cx="25" cy="25" r={radius} fill="none" stroke="#2A2A2A" strokeWidth="4" />
          {/* Progress */}
          <motion.circle
            cx="25" cy="25" r={radius}
            fill="none"
            stroke={color}
            strokeWidth="4"
            strokeLinecap="round"
            strokeDasharray={circumference}
            initial={{ strokeDashoffset: circumference }}
            animate={{ strokeDashoffset: dashOffset }}
            transition={{ duration: 0.8, ease: "easeOut" }}
          />
        </svg>
        {/* Score label in center */}
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={cn("font-bold tabular-nums", sz.text)} style={{ color }}>
            {pct}
          </span>
        </div>
      </div>

      {/* Info */}
      {(showTier || showLabel) && (
        <div>
          {showLabel && (
            <p className="text-xs text-text-quaternary">Trust Score</p>
          )}
          <p className="font-semibold text-text-primary text-sm">{formatTrust(score)}</p>
          {showTier && (
            <div className="flex items-center gap-1 mt-0.5">
              <Shield className={cn(sz.icon)} style={{ color }} />
              <span className="text-2xs font-medium" style={{ color }}>
                {TIER_LABELS[tier]}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Full panel variant ─────────────────────────────────────────────────────────

interface TrustScorePanelProps {
  score:     number;
  agentDid?: string;
}

const BREAKDOWN_LABELS: Record<string, string> = {
  execution_score:   "Execution",
  sla_score:         "SLA",
  endorsement_score: "Endorsements",
  audit_score:       "Audit",
  security_score:    "Security",
};

const BREAKDOWN_WEIGHTS: Record<string, string> = {
  execution_score:   "35%",
  sla_score:         "25%",
  endorsement_score: "20%",
  audit_score:       "12%",
  security_score:    "8%",
};

export function TrustScorePanel({ score, agentDid }: TrustScorePanelProps) {
  const tier  = trustTierFromScore(score);
  const color = trustTierColor(tier);

  return (
    <div className="card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-text-tertiary" />
          Trust Score
        </h3>
        <span
          className="badge text-2xs"
          style={{ backgroundColor: `${color}22`, color, border: `1px solid ${color}44` }}
        >
          {tier}
        </span>
      </div>

      <div className="flex justify-center">
        <TrustScore score={score} size="lg" showTier showLabel />
      </div>

      {/* Static weight breakdown when no breakdown data */}
      <div className="space-y-2">
        {Object.entries(BREAKDOWN_LABELS).map(([key, label]) => (
          <div key={key} className="flex items-center gap-2">
            <span className="text-xs text-text-tertiary w-28 shrink-0">{label}</span>
            <div className="flex-1 h-1.5 bg-surface-tertiary rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{ width: BREAKDOWN_WEIGHTS[key], backgroundColor: color, opacity: 0.7 }}
              />
            </div>
            <span className="text-2xs text-text-quaternary w-8 text-right">
              {BREAKDOWN_WEIGHTS[key]}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
