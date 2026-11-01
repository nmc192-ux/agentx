import type { Metadata } from "next";
import { ComingLater } from "@/components/layout/ComingLater";
import { FEATURE_COLLECTIVES } from "@/lib/flags";

// Hidden layer gate (lib/layers.ts): with the flag off, every page under
// /groups shows "coming later" and is kept out of search results.
export const metadata: Metadata = FEATURE_COLLECTIVES ? {} : { robots: { index: false } };

export default function GroupsLayout({ children }: { children: React.ReactNode }) {
  if (!FEATURE_COLLECTIVES) return <ComingLater layer="collectives" />;
  return children;
}
