import type { Metadata } from "next";
import { ComingLater } from "@/components/layout/ComingLater";
import { FEATURE_LEADERBOARD } from "@/lib/flags";

// Hidden layer gate (lib/layers.ts): with the flag off, every page under
// /leaderboard shows "coming later" and is kept out of search results.
export const metadata: Metadata = FEATURE_LEADERBOARD ? {} : { robots: { index: false } };

export default function LeaderboardLayout({ children }: { children: React.ReactNode }) {
  if (!FEATURE_LEADERBOARD) return <ComingLater layer="leaderboard" />;
  return children;
}
