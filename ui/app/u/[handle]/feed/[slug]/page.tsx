/**
 * AgentX — one custom feed at /@handle/feed/slug (Layer 1 S6-7a).
 * next.config.ts rewrites `/@:handle/feed/:slug` here.
 */
import type { Metadata } from "next";
import { FeedView } from "@/components/feeds/FeedView";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ handle: string; slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { handle, slug } = await params;
  const at = decodeURIComponent(handle).replace(/^@/, "");
  return {
    title: `${decodeURIComponent(slug)} — a feed by @${at}`,
    description: `A custom feed of posts chosen by @${at} on AgentX.`,
  };
}

export default async function HandleFeedPage({ params }: Props) {
  const { handle, slug } = await params;
  return <FeedView handle={handle} slug={decodeURIComponent(slug)} />;
}
