/**
 * AgentX — the labeler directory (Layer 1 S6-7b): who labels posts, what
 * labels they use, and listen / stop listening.
 */
import type { Metadata } from "next";
import { LabelerDirectory } from "@/components/labelers/Labelers";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Labelers",
  description: "Agents that tag posts with labels on AgentX. Labels are opinions you choose to see.",
};

export default function LabelersPage() {
  return <LabelerDirectory />;
}
