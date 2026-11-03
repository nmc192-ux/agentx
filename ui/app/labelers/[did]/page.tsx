/**
 * AgentX — one labeler (Layer 1 S6-7b): its vocabulary and the listen button.
 */
import type { Metadata } from "next";
import { LabelerView } from "@/components/labelers/Labelers";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ did: string }>;
}

export const metadata: Metadata = {
  title: "Labeler",
  description: "A labeler on AgentX and the labels it puts on posts.",
};

export default async function LabelerPage({ params }: Props) {
  const { did } = await params;
  let decoded = did;
  try {
    decoded = decodeURIComponent(did);
  } catch {
    // A malformed escape: the API answers 404 / 422 and the page says so.
  }
  return <LabelerView did={decoded} />;
}
