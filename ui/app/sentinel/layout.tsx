import type { Metadata } from "next";
import { ComingLater } from "@/components/layout/ComingLater";
import { FEATURE_SENTINEL } from "@/lib/flags";

// Hidden layer gate (lib/layers.ts): with the flag off, every page under
// /sentinel shows "coming later" and is kept out of search results.
export const metadata: Metadata = FEATURE_SENTINEL ? {} : { robots: { index: false } };

export default function SentinelLayout({ children }: { children: React.ReactNode }) {
  if (!FEATURE_SENTINEL) return <ComingLater layer="sentinel" />;
  return children;
}
