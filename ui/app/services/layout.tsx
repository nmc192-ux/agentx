import type { Metadata } from "next";
import { ComingLater } from "@/components/layout/ComingLater";
import { FEATURE_SERVICES } from "@/lib/flags";

// Hidden layer gate (lib/layers.ts): with the flag off, every page under
// /services shows "coming later" and is kept out of search results.
export const metadata: Metadata = FEATURE_SERVICES ? {} : { robots: { index: false } };

export default function ServicesLayout({ children }: { children: React.ReactNode }) {
  if (!FEATURE_SERVICES) return <ComingLater layer="services" />;
  return children;
}
