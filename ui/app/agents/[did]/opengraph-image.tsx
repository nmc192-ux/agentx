/**
 * AgentX — Dynamic OG image for /agents/[did]
 *
 * Renders a 1200×630 card with:
 *   • Agent avatar (initial-based gradient)
 *   • Display name + DID
 *   • Trust score ring + tier badge
 *   • Governance role
 *   • AgentX branding + "AI Agent Network" tagline
 *
 * Uses next/og ImageResponse — no external dependencies needed.
 */
import { ImageResponse } from "next/og";
import type { GovernanceRole, AgentTier } from "@/types";

export const runtime = "edge";
export const alt     = "AgentX agent profile";
export const size    = { width: 1200, height: 630 };
export const contentType = "image/png";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "https://agentx-platform.fly.dev";

const TIER_COLOR: Record<AgentTier, string> = {
  STANDARD:   "#64748B",
  PRO:        "#A855F7",
  ENTERPRISE: "#F59E0B",
};

const ROLE_LABEL: Record<GovernanceRole, string> = {
  FOUNDER:  "Founder",
  OPERATOR: "Operator",
  MEMBER:   "Member",
  OBSERVER: "Observer",
};

// Deterministic gradient from DID string
function didGradient(did: string): [string, string] {
  const colours: [string, string][] = [
    ["#06B6D4", "#6366F1"],
    ["#8B5CF6", "#EC4899"],
    ["#22C55E", "#3B82F6"],
    ["#F59E0B", "#EF4444"],
    ["#06B6D4", "#A855F7"],
    ["#F97316", "#EF4444"],
  ];
  const idx = did.charCodeAt(did.length - 1) % colours.length;
  return colours[idx]!;
}

type AgentData = {
  agent_did:       string;
  display_name:    string;
  bio?:            string;
  trust_score:     number;
  tier:            AgentTier;
  governance_role: GovernanceRole;
  // social counts injected by some endpoints
  followers_count?: number;
  following_count?: number;
};

async function fetchAgent(rawDid: string): Promise<AgentData | null> {
  const did = decodeURIComponent(rawDid);
  try {
    const res = await fetch(`${API_BASE}/agents/${encodeURIComponent(did)}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max - 1) + "…" : str;
}

export default async function Image({
  params,
}: {
  params: { did: string };
}) {
  const agent = await fetchAgent(params.did);

  // Fallback
  if (!agent) {
    return new ImageResponse(
      (
        <div
          style={{
            width: "100%",
            height: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "#0F172A",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
            <div
              style={{
                width: 64,
                height: 64,
                borderRadius: 16,
                background: "rgba(6,182,212,0.2)",
                border: "1px solid rgba(6,182,212,0.3)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <span style={{ fontSize: 32, color: "#06B6D4" }}>⚡</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <span style={{ fontSize: 36, fontWeight: 800, color: "#F1F5F9" }}>AgentX</span>
              <span style={{ fontSize: 18, color: "#94A3B8", marginTop: 4 }}>
                AI Agent Network
              </span>
            </div>
          </div>
        </div>
      ),
      { ...size },
    );
  }

  const [gradA, gradB]  = didGradient(agent.agent_did);
  const initial         = (agent.display_name[0] ?? "A").toUpperCase();
  const trustPct        = Math.round(agent.trust_score * 100);
  const tierColor       = TIER_COLOR[agent.tier] ?? "#64748B";
  const roleLabel       = ROLE_LABEL[agent.governance_role] ?? agent.governance_role;
  const shortDid        = agent.agent_did.length > 40
    ? agent.agent_did.slice(0, 37) + "…"
    : agent.agent_did;
  const bioText         = agent.bio ? truncate(agent.bio, 140) : null;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: "#0F172A",
          padding: "56px 64px",
          fontFamily: "system-ui, sans-serif",
          position: "relative",
        }}
      >
        {/* Background glow */}
        <div
          style={{
            position: "absolute",
            top: -160,
            left: -80,
            width: 500,
            height: 500,
            borderRadius: "50%",
            background: `radial-gradient(circle, ${gradA}12 0%, transparent 70%)`,
            pointerEvents: "none",
          }}
        />

        {/* Header row */}
        <div style={{ display: "flex", alignItems: "center", gap: 32, marginBottom: 36 }}>
          {/* Avatar */}
          <div
            style={{
              width: 96,
              height: 96,
              borderRadius: 24,
              background: `linear-gradient(135deg, ${gradA}, ${gradB})`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 44,
              fontWeight: 800,
              color: "#fff",
              flexShrink: 0,
            }}
          >
            {initial}
          </div>

          {/* Name + DID */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8, flex: 1 }}>
            <div
              style={{
                fontSize: 42,
                fontWeight: 800,
                color: "#F1F5F9",
                lineHeight: 1.1,
              }}
            >
              {truncate(agent.display_name, 32)}
            </div>
            <div
              style={{
                fontSize: 16,
                color: "#475569",
                fontFamily: "monospace",
              }}
            >
              {shortDid}
            </div>
          </div>
        </div>

        {/* Bio */}
        {bioText && (
          <div
            style={{
              fontSize: 22,
              color: "#94A3B8",
              lineHeight: 1.5,
              marginBottom: 32,
              maxWidth: "85%",
            }}
          >
            {bioText}
          </div>
        )}

        {/* Stats pills */}
        <div
          style={{
            display: "flex",
            gap: 16,
            flexWrap: "wrap",
            marginTop: bioText ? 0 : 8,
            flex: 1,
            alignItems: "flex-start",
          }}
        >
          {/* Trust score */}
          <div
            style={{
              padding: "10px 22px",
              borderRadius: 999,
              background: "#1E293B",
              border: "1px solid #334155",
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            <div
              style={{
                width: 12,
                height: 12,
                borderRadius: "50%",
                background: "#A855F7",
              }}
            />
            <span style={{ fontSize: 18, fontWeight: 700, color: "#A855F7" }}>
              {trustPct}%
            </span>
            <span style={{ fontSize: 15, color: "#64748B" }}>trust</span>
          </div>

          {/* Tier */}
          <div
            style={{
              padding: "10px 22px",
              borderRadius: 999,
              background: "#1E293B",
              border: `1px solid ${tierColor}44`,
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            <div
              style={{
                width: 12,
                height: 12,
                borderRadius: "50%",
                background: tierColor,
              }}
            />
            <span style={{ fontSize: 15, fontWeight: 600, color: tierColor }}>
              {agent.tier}
            </span>
          </div>

          {/* Role */}
          <div
            style={{
              padding: "10px 22px",
              borderRadius: 999,
              background: "#1E293B",
              border: "1px solid #334155",
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            <span style={{ fontSize: 15, color: "#94A3B8" }}>{roleLabel}</span>
          </div>

          {/* Followers */}
          {(agent.followers_count ?? 0) > 0 && (
            <div
              style={{
                padding: "10px 22px",
                borderRadius: 999,
                background: "#1E293B",
                border: "1px solid #334155",
                display: "flex",
                alignItems: "center",
                gap: 10,
              }}
            >
              <span style={{ fontSize: 18, fontWeight: 700, color: "#06B6D4" }}>
                {agent.followers_count?.toLocaleString()}
              </span>
              <span style={{ fontSize: 15, color: "#64748B" }}>followers</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginTop: 36,
            paddingTop: 24,
            borderTop: "1px solid #1E293B",
          }}
        >
          {/* Tagline */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: "#06B6D4",
              }}
            />
            <span style={{ fontSize: 16, color: "#64748B" }}>
              AI Agent Network · agentx.social
            </span>
          </div>

          {/* Branding */}
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 12,
                background: "rgba(6,182,212,0.15)",
                border: "1px solid rgba(6,182,212,0.25)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 22,
              }}
            >
              ⚡
            </div>
            <span style={{ fontSize: 22, fontWeight: 800, color: "#F1F5F9" }}>AgentX</span>
          </div>
        </div>
      </div>
    ),
    { ...size },
  );
}
