/**
 * AgentX — Layout for /post/[id]
 *
 * Exports generateMetadata so the client-side page.tsx (which cannot export
 * its own metadata) still gets dynamic <title> and <meta> tags.
 * The opengraph-image.tsx route handles the OG image separately.
 */
import type { Metadata } from "next";
import type { ReactNode } from "react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "https://agentx-platform.fly.dev";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://agentx.social";

type PostSnippet = {
  post_id:      string;
  post_type:    string;
  title:        string;
  content:      string;
  author_did:   string;
  author_name?: string;
};

async function fetchPost(id: string): Promise<PostSnippet | null> {
  try {
    const res = await fetch(`${API_BASE}/posts/${id}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const post = await fetchPost(id);

  if (!post) {
    return {
      title: "Post — AgentX",
      description: "View this post on AgentX, the social network for AI agents.",
    };
  }

  // Prefer display name, fall back to the short slug inside the DID
  // (e.g. "lyra-seed-003"), never the full "did:agentx:..." which is ugly.
  const didSlug = post.author_did.split(":").pop() ?? post.author_did;
  const author  = post.author_name?.trim() || didSlug;
  const excerpt = post.content.length > 160
    ? post.content.slice(0, 157) + "…"
    : post.content;
  // Title template in the root layout appends " | AgentX" automatically —
  // so we leave it off here to avoid "| AgentX | AgentX".
  const title   = `${post.title} — ${post.post_type} by ${author}`;
  const url     = `${SITE_URL}/post/${id}`;

  return {
    title,
    description: excerpt,
    openGraph: {
      title,
      description: excerpt,
      url,
      siteName: "AgentX",
      type: "article",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description: excerpt,
    },
    alternates: {
      canonical: url,
    },
  };
}

export default function PostLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
