import type { Metadata } from "next";
import { ComingLater } from "@/components/layout/ComingLater";
import { FEATURE_SPOTLIGHT } from "@/lib/flags";

// Hidden layer gate (lib/layers.ts): with the flag off, every page under
// /spotlight shows "coming later" and is kept out of search results.
export const metadata: Metadata = FEATURE_SPOTLIGHT ? {} : { robots: { index: false } };

export default function SpotlightLayout({ children }: { children: React.ReactNode }) {
  if (!FEATURE_SPOTLIGHT) return <ComingLater layer="spotlight" />;
  return children;
}
