import type { Metadata } from "next";
import { ComingLater } from "@/components/layout/ComingLater";
import { FEATURE_GOVERNANCE } from "@/lib/flags";

// Hidden layer gate (lib/layers.ts): with the flag off, every page under
// /governance shows "coming later" and is kept out of search results.
export const metadata: Metadata = FEATURE_GOVERNANCE ? {} : { robots: { index: false } };

export default function GovernanceLayout({ children }: { children: React.ReactNode }) {
  if (!FEATURE_GOVERNANCE) return <ComingLater layer="governance" />;
  return children;
}
