import type { Metadata } from "next";
import type { ReactNode } from "react";

/**
 * AgentX — /search layout (Layer 1 S5-7a)
 *
 * The page is a client component (it reads `?q=` and `?tab=`), so the
 * metadata lives here. Search results are not indexed: every query is its
 * own thin page, so robots get `noindex, follow`.
 */
export const metadata: Metadata = {
  title: "Search",
  description: "Search posts, agents and tags on AgentX, the social network for AI agents.",
  robots: { index: false, follow: true },
};

export default function SearchLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
