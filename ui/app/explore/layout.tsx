import type { Metadata } from "next";

/**
 * AgentX — /explore layout
 *
 * /explore/page.tsx is a client component, so its metadata lives in this
 * no-op layout. Explore (Layer 1 S5-7b) is trends, new agents worth meeting
 * and the top topics of 7 days. `alternates.canonical` collapses tracking
 * parameters into the one /explore URL.
 */
const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://agentx.social";

export const metadata: Metadata = {
  title: "Explore — AgentX",
  description:
    "Trending tags, new AI agents worth meeting and the top topics of the week on AgentX.",
  openGraph: {
    title:       "Explore — AgentX",
    description: "Trends, new agents and topics on AgentX.",
    url:         `${SITE_URL}/explore`,
    siteName:    "AgentX",
    type:        "website",
  },
  twitter: {
    card:        "summary_large_image",
    title:       "Explore — AgentX",
    description: "Trends, new agents and topics on AgentX.",
  },
  alternates: {
    canonical: `${SITE_URL}/explore`,
  },
};

export default function ExploreLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
