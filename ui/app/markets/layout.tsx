import type { Metadata } from "next";
import { ComingLater } from "@/components/layout/ComingLater";
import { FEATURE_ECONOMY } from "@/lib/flags";

// Hidden layer gate (lib/layers.ts): with the flag off, every page under
// /markets shows "coming later" and is kept out of search results.
export const metadata: Metadata = FEATURE_ECONOMY ? {} : { robots: { index: false } };

export default function MarketsLayout({ children }: { children: React.ReactNode }) {
  if (!FEATURE_ECONOMY) return <ComingLater layer="economy" />;
  return children;
}
