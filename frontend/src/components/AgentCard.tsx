"use client";

/**
 * AgentX — AgentCard component
 * Two variants:
 *   "compact" — used in lists/search results
 *   "full"    — used in sidebar / profile header
 */
import Link from "next/link";
import { motion } from "framer-motion";
import { Shield, Star, Clock } from "lucide-react";
import { cn, shortDid, formatDate, formatTrust } from "@/lib/utils";
import { trustTierFromScore, trustTierColor, type Agent } from "@/types";
import { TrustScore } from "./TrustScore";

// ── Compact card ──────────────────────────────────────────────────────────────

interface AgentCardCompactProps {
  agent:     Agent;
  className?: string;
}

export function AgentCardCompact({ agent, className }: AgentCardCompactProps) {
  const tier  = trustTierFromScore(agent.trust_score);
  const color = trustTierColor(tier);

  return (
    <Link
      href={`/profile/${encodeURIComponent(agent.agent_did)}`}
      className={cn("card-hover flex items-center gap-3 p-3", className)}
    >
      {/* Avatar */}
      <div
        className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold shrink-0"
        style={{ backgroundColor: `${color}22`, color }}
      >
        {agent.display_name[0]?.toUpperCase() ?? "A"}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-text-primary truncate">
          {agent.display_name}
        </p>
        <p className="text-2xs text-text-quaternary font-mono truncate">
          {shortDid(agent.agent_did)}
        </p>
      </div>

      {/* Trust */}
      <div className="shrink-0 text-right">
        <p className="text-xs font-semibold tabular-nums" style={{ color }}>
          {formatTrust(agent.trust_score)}
        </p>
        <p className="text-2xs text-text-quaternary capitalize">{tier}</p>
      </div>
    </Link>
  );
}

// ── Full card ─────────────────────────────────────────────────────────────────

interface AgentCardFullProps {
  agent:            Agent;
  showCapabilities?: boolean;
  showActivity?:     boolean;
  interactive?:      boolean;
  className?:        string;
}

export function AgentCard({
  agent,
  showCapabilities = false,
  showActivity     = false,
  interactive      = true,
  className,
}: AgentCardFullProps) {
  const tier  = trustTierFromScore(agent.trust_score);
  const color = trustTierColor(tier);

  const content = (
    <div className={cn("card p-4 space-y-4", interactive && "card-hover", className)}>
      {/* Header */}
      <div className="flex items-start gap-3">
        <div
          className="w-12 h-12 rounded-xl flex items-center justify-center text-lg font-bold shrink-0"
          style={{ backgroundColor: `${color}22`, color }}
        >
          {agent.display_name[0]?.toUpperCase() ?? "A"}
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-text-primary truncate">{agent.display_name}</h3>
          <p className="text-xs text-text-quaternary font-mono truncate mt-0.5">
            {agent.agent_did}
          </p>
          <div className="flex items-center gap-2 mt-1">
            <span
              className="badge"
              style={{ backgroundColor: `${color}22`, color, border: `1px solid ${color}44` }}
            >
              {agent.governance_role}
            </span>
            <span className="badge bg-surface-tertiary text-text-tertiary border border-border-primary">
              {agent.tier}
            </span>
          </div>
        </div>
      </div>

      {/* Bio */}
      {agent.bio && (
        <p className="text-sm text-text-secondary line-clamp-2">{agent.bio}</p>
      )}

      {/* Trust score */}
      <TrustScore score={agent.trust_score} size="sm" showTier className="mt-2" />

      {/* Capabilities */}
      {showCapabilities && agent.capabilities && agent.capabilities.length > 0 && (
        <div>
          <p className="text-2xs text-text-quaternary mb-1.5 uppercase tracking-wider font-medium">
            Capabilities
          </p>
          <div className="flex flex-wrap gap-1">
            {agent.capabilities.slice(0, 5).map((cap) => (
              <span
                key={cap.capability_id}
                className="badge bg-surface-secondary text-text-tertiary border border-border-primary"
              >
                {cap.capability_name.split(".").slice(-2).join(".")}
              </span>
            ))}
            {agent.capabilities.length > 5 && (
              <span className="badge bg-surface-secondary text-text-quaternary">
                +{agent.capabilities.length - 5}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Activity */}
      {showActivity && (
        <div className="flex items-center gap-1.5 text-2xs text-text-quaternary border-t border-border-primary pt-3">
          <Clock className="w-3 h-3" />
          <span>Joined {formatDate(agent.created_at)}</span>
        </div>
      )}
    </div>
  );

  if (interactive) {
    return (
      <Link href={`/profile/${encodeURIComponent(agent.agent_did)}`}>
        {content}
      </Link>
    );
  }
  return content;
}
