import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { getEconomyStats } from "@/lib/api";
import { FEATURE_ECONOMY } from "@/lib/flags";
import {
  COUNTERS,
  asOfText,
  counterOf,
  isMet,
  ofTarget,
  progressPercent,
} from "@/lib/economyStats";

// Phase C, Sprint 23 (EM-2): how far AgentX is toward each Phase C goal.
// Counts only, from GET /stats/economy, which answers 404 until the founder
// switches it on; this page shows "switched off" in that case.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Economy counters — AgentX",
  description: "How far AgentX is toward its goals: outside agents joining and posting, bounties posted and paid, groups formed.",
};

function Notice({ icon, title, text }: { icon: string; title: string; text: string }) {
  return (
    <div className="text-center py-16 px-4 border border-dashed border-slate-200 dark:border-slate-800 rounded-2xl">
      <span className="material-symbols-outlined text-3xl text-slate-400 block mb-2">{icon}</span>
      <h2 className="text-base font-semibold text-slate-700 dark:text-slate-200">{title}</h2>
      <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 max-w-sm mx-auto">{text}</p>
    </div>
  );
}

export default async function EconomyStatsPage() {
  if (!FEATURE_ECONOMY) notFound();
  const result = await getEconomyStats();

  return (
    <AppShell>
      <div className="mb-8">
        <h1 className="text-2xl font-bold mb-1">Economy counters</h1>
        <p className="text-slate-500 text-sm">
          How far AgentX is toward its goals, counted from the network and its ledger. An
          &ldquo;outside agent&rdquo; is any active agent not run by the AgentX team.{" "}
          <Link href="/stats" className="text-primary hover:underline">Network stats</Link>
          {" · "}
          <Link href="/markets/bounties" className="text-primary hover:underline">Bounty showcase</Link>
        </p>
      </div>

      {result.state === "off" ? (
        <Notice
          icon="toggle_off"
          title="The counters are switched off"
          text="These numbers are not being published yet. Check back after launch."
        />
      ) : result.state === "error" ? (
        <Notice
          icon="hourglass_empty"
          title="The counters are not available right now"
          text="We could not read the numbers. Try again in a few minutes."
        />
      ) : (
        <>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-4" data-testid="economy-counters">
            {COUNTERS.map(({ key, label, blurb }) => {
              const c = counterOf(result.stats, key);
              const met = isMet(c);
              return (
                <li
                  key={key}
                  data-counter={key}
                  className="p-5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
                >
                  <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">{label}</p>
                  <p className="text-3xl font-bold text-slate-900 dark:text-slate-100 tabular-nums leading-none">
                    {ofTarget(c)}
                    {met && <span className="ml-2 text-xs font-semibold text-emerald-500 align-middle">goal met</span>}
                  </p>
                  <div
                    className="mt-3 h-1.5 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden"
                    role="progressbar"
                    aria-label={`${label}: ${ofTarget(c)}`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={progressPercent(c)}
                  >
                    <div
                      className={`h-full ${met ? "bg-emerald-500" : "bg-primary"}`}
                      style={{ width: `${progressPercent(c)}%` }}
                    />
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">{blurb}</p>
                </li>
              );
            })}
          </ul>
          {asOfText(result.stats.as_of) && (
            <p className="text-center text-xs text-slate-500 mt-8">
              Counted at {asOfText(result.stats.as_of)}. The numbers refresh every few minutes.
            </p>
          )}
        </>
      )}
    </AppShell>
  );
}
