import type { Metadata } from "next";
import { ComingLater } from "@/components/layout/ComingLater";
import { FEATURE_CONSTELLATION } from "@/lib/flags";

// Hidden layer gate (lib/layers.ts): with the flag off, every page under
// /graph shows "coming later" and is kept out of search results.
export const metadata: Metadata = FEATURE_CONSTELLATION ? {} : { robots: { index: false } };

export default function GraphLayout({ children }: { children: React.ReactNode }) {
  if (!FEATURE_CONSTELLATION) return <ComingLater layer="constellation" />;
  return children;
}
