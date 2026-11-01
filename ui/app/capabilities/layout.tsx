import type { Metadata } from "next";
import { ComingLater } from "@/components/layout/ComingLater";
import { FEATURE_CAPABILITIES } from "@/lib/flags";

// Hidden layer gate (lib/layers.ts): with the flag off, every page under
// /capabilities shows "coming later" and is kept out of search results.
export const metadata: Metadata = FEATURE_CAPABILITIES ? {} : { robots: { index: false } };

export default function CapabilitiesLayout({ children }: { children: React.ReactNode }) {
  if (!FEATURE_CAPABILITIES) return <ComingLater layer="capabilities" />;
  return children;
}
