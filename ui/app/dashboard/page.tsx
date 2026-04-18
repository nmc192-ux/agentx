"use client";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { AgentRoster } from "@/components/ops/AgentRoster";
import { UnifiedFeed } from "@/components/ops/UnifiedFeed";
import { SystemStats } from "@/components/ops/SystemStats";
import { ComposeBox } from "@/components/ops/ComposeBox";
import { LivePulse } from "@/components/pulse/LivePulse";
import { FEATURE_ECONOMY } from "@/lib/flags";

export default function DashboardPage() {
  if (!FEATURE_ECONOMY) notFound();
  return (
    <AppShell wide>
      {/* Live Pulse — platform vitals */}
      <div className="mb-4 -mt-4">
        <LivePulse />
      </div>

      {/* Negative margin to counteract AppShell's py-8, then fill viewport height */}
      <div className="-mb-8 h-[calc(100vh-200px)] flex overflow-hidden">
        <AgentRoster />

        <div className="flex-1 flex flex-col overflow-hidden border-x border-slate-200 dark:border-slate-800">
          <UnifiedFeed />
          <ComposeBox />
        </div>

        <SystemStats />
      </div>
    </AppShell>
  );
}
