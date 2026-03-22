"use client";
import { AppShell } from "@/components/layout/AppShell";
import { AgentRoster } from "@/components/ops/AgentRoster";
import { UnifiedFeed } from "@/components/ops/UnifiedFeed";
import { SystemStats } from "@/components/ops/SystemStats";
import { ComposeBox } from "@/components/ops/ComposeBox";

export default function DashboardPage() {
  return (
    <AppShell wide>
      {/* Negative margin to counteract AppShell's py-8, then fill viewport height */}
      <div className="-mt-8 -mb-8 h-[calc(100vh-64px)] flex overflow-hidden">
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
