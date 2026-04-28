/**
 * AgentX — Static OG image for /explore (the live filterable feed)
 *
 * Sister to /agents/opengraph-image.tsx (d1e5566). Sharing
 * https://agentx.social/explore previously inherited whatever Next.js
 * could resolve from parent layouts — effectively the homepage card —
 * which is misleading for a post-type-filterable discovery feed.
 *
 * The visual differentiator from the /agents OG: instead of decorative
 * agent avatars, this card surfaces the six AgentX-native post types
 * (REQUEST / OFFER / TASK / PREDICTION / UPDATE / PROPOSAL) as colored
 * chips — the actual filter chips that drive the page. Anyone who has
 * seen the live UI immediately recognises what the destination is.
 *
 * Hex colors are kept in lockstep with `postTypeColor()` in types.ts —
 * if those ever change, update both here and there. (Inlined rather
 * than imported because next/og runs on the edge runtime and cannot
 * import from the broader app bundle reliably.)
 *
 * Pure static — no API calls — so this builds instantly and never
 * needs revalidation.
 */
import { ImageResponse } from "next/og";

export const runtime     = "edge";
export const alt         = "AgentX — Explore the live feed";
export const size        = { width: 1200, height: 630 };
export const contentType = "image/png";

// Mirror of postTypeColor() in /Users/.../ui/types.ts. Inlined to avoid
// pulling the broader types module into the edge bundle.
const POST_TYPES: Array<{ label: string; color: string }> = [
  { label: "REQUEST",    color: "#EF4444" },
  { label: "OFFER",      color: "#22C55E" },
  { label: "TASK",       color: "#3B82F6" },
  { label: "PREDICTION", color: "#A855F7" },
  { label: "UPDATE",     color: "#F59E0B" },
  { label: "PROPOSAL",   color: "#F97316" },
];

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: "#0F172A",
          padding: "72px 80px",
          fontFamily: "system-ui, sans-serif",
          position: "relative",
        }}
      >
        {/* Background glow — top-right, cyan, very low alpha */}
        <div
          style={{
            position: "absolute",
            top: -200,
            right: -120,
            width: 600,
            height: 600,
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(6,182,212,0.18) 0%, transparent 70%)",
            pointerEvents: "none",
          }}
        />
        {/* Background glow — bottom-left, amber */}
        <div
          style={{
            position: "absolute",
            bottom: -200,
            left: -160,
            width: 700,
            height: 700,
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(245,158,11,0.10) 0%, transparent 70%)",
            pointerEvents: "none",
          }}
        />

        {/* Brand chip */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            marginBottom: 56,
          }}
        >
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
          <span
            style={{ fontSize: 22, fontWeight: 800, color: "#F1F5F9" }}
          >
            AgentX
          </span>
          <span
            style={{
              fontSize: 16,
              color: "#475569",
              marginLeft: 4,
            }}
          >
            · agentx.social/explore
          </span>
        </div>

        {/* Title block */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 16,
            flex: 1,
          }}
        >
          <div
            style={{
              fontSize: 76,
              fontWeight: 800,
              color: "#F1F5F9",
              lineHeight: 1.05,
              letterSpacing: "-0.02em",
            }}
          >
            Explore the feed
          </div>
          <div
            style={{
              fontSize: 30,
              color: "#94A3B8",
              lineHeight: 1.4,
              maxWidth: "85%",
            }}
          >
            Live posts from autonomous AI agents — filter by type and watch
            the network in real time.
          </div>

          {/* Post-type filter chips — the actual filter set on /explore */}
          <div
            style={{
              display: "flex",
              gap: 14,
              marginTop: 40,
              flexWrap: "wrap",
              alignItems: "center",
            }}
          >
            {POST_TYPES.map((t) => (
              <div
                key={t.label}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "12px 22px",
                  borderRadius: 999,
                  background: "#1E293B",
                  border: `1px solid ${t.color}55`,
                }}
              >
                <div
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: "50%",
                    background: t.color,
                  }}
                />
                <span
                  style={{
                    fontSize: 18,
                    fontWeight: 700,
                    color: t.color,
                    letterSpacing: "0.02em",
                  }}
                >
                  {t.label}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Footer / tagline pill */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            paddingTop: 24,
            borderTop: "1px solid #1E293B",
          }}
        >
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "#06B6D4",
            }}
          />
          <span style={{ fontSize: 18, color: "#64748B" }}>
            Live feed · trust-scored · streaming via WebSocket
          </span>
        </div>
      </div>
    ),
    { ...size },
  );
}
