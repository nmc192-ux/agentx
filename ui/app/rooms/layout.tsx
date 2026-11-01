import type { Metadata } from "next";
import { ComingLater } from "@/components/layout/ComingLater";
import { FEATURE_ROOMS } from "@/lib/flags";

// Hidden layer gate (lib/layers.ts): with the flag off, every page under
// /rooms shows "coming later" and is kept out of search results.
export const metadata: Metadata = FEATURE_ROOMS ? {} : { robots: { index: false } };

export default function RoomsLayout({ children }: { children: React.ReactNode }) {
  if (!FEATURE_ROOMS) return <ComingLater layer="rooms" />;
  return children;
}
