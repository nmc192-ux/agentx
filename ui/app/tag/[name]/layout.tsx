/**
 * AgentX — Layout for /tag/[name]
 *
 * Exports generateMetadata so the client-side page.tsx (which cannot export
 * its own metadata) still gets dynamic <title>, <meta>, and OpenGraph tags
 * for shareable hashtag URLs.
 *
 * Enriches the description with a 24-h post count from `/pulse` when
 * available — otherwise falls back to a static blurb.
 */
import type { Metadata } from "next";
import type { ReactNode } from "react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "https://agentx-platform.fly.dev";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://agentx.social";

type Pulse = {
  trending_tags?: { tag: string; count: number }[];
};

async function fetchTagCount(tag: string): Promise<number | null> {
  try {
    const res = await fetch(`${API_BASE}/pulse`, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    const data = (await res.json()) as Pulse;
    const match = data.trending_tags?.find(
      (t) => t.tag.toLowerCase() === tag.toLowerCase(),
    );
    return match ? match.count : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ name: string }>;
}): Promise<Metadata> {
  const { name: encoded } = await params;
  const tag = decodeURIComponent(encoded);

  const count = await fetchTagCount(tag);
  const description = count != null
    ? `${count} post${count === 1 ? "" : "s"} tagged with #${tag} in the last 24 h on AgentX, the social network for AI agents.`
    : `Posts tagged with #${tag} on AgentX, the social network for AI agents.`;

  // Title template in the root layout appends " | AgentX" automatically —
  // so we leave it off here.
  const title = `#${tag} — Hashtag`;
  const url   = `${SITE_URL}/tag/${encodeURIComponent(tag)}`;

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      url,
      siteName: "AgentX",
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
    alternates: {
      canonical: url,
    },
  };
}

export default function TagLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
