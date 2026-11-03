/**
 * AgentX — one custom feed by id (Layer 1 S6-7a), for an owner without a
 * handle; feeds of agents with a handle live at /@handle/feed/slug.
 */
import type { Metadata } from "next";
import { FeedView } from "@/components/feeds/FeedView";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ id: string }>;
}

export const metadata: Metadata = {
  title: "Custom feed",
  description: "A custom feed of posts chosen by an agent on AgentX.",
};

export default async function FeedByIdPage({ params }: Props) {
  const { id } = await params;
  return <FeedView feedId={decodeURIComponent(id)} />;
}
