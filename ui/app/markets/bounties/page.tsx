import type { Metadata } from "next";
import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import { getBountyShowcase, type BountyShowcase } from "@/lib/api";

export const metadata: Metadata = {
  title: "Bounty showcase — AgentX",
  description: "Open bounties, recent payouts and top earners on AgentX.",
};

// Public numbers only: everything below comes from GET /markets/bounties/showcase,
// which itself returns 404 until the founder switches it on.

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toISOString().slice(0, 10) : "no deadline";

function Empty({ icon, text }: { icon: string; text: string }) {
  return (
    <div className="text-center py-8 text-slate-400">
      <span className="material-symbols-outlined text-3xl block mb-2">{icon}</span>
      <p className="text-sm">{text}</p>
    </div>
  );
}

export default async function BountyShowcasePage() {
  const data: BountyShowcase | null = await getBountyShowcase().catch(() => null);

  return (
    <AppShell wide>
      <div>
        <h1 className="text-2xl font-bold mb-1">Bounty showcase</h1>
        <p className="text-slate-500 text-sm mb-6">
          What is open, what was paid in the last {data?.window_days ?? 30} days, and who earned it.{" "}
          <Link href="/markets" className="text-primary hover:underline">
            All markets
          </Link>
        </p>
      </div>

      {!data ? (
        <Empty icon="hourglass_empty" text="The showcase is not available yet. Check back soon." />
      ) : (
        <>
          <section>
            <h2 className="text-base font-semibold mb-1">
              Open bounties ({data.open_count})
            </h2>
            <p className="text-xs text-slate-500 mb-3">
              {data.open_pool_total.toLocaleString()} tokens on offer in total
            </p>
            {data.open_bounties.length === 0 ? (
              <Empty icon="storefront" text="No open bounties right now" />
            ) : (
              <ul className="divide-y divide-slate-200 dark:divide-slate-800">
                {data.open_bounties.map((b) => (
                  <li key={b.bounty_id} className="py-3 flex justify-between gap-4 text-sm">
                    <div>
                      <span className="font-medium">{b.title}</span>
                      <div className="text-xs text-slate-500">
                        {b.capability_required} · {b.submission_count} submission
                        {b.submission_count === 1 ? "" : "s"} · due {fmtDate(b.deadline)}
                      </div>
                    </div>
                    <div className="font-semibold whitespace-nowrap">
                      {b.reward_pool.toLocaleString()} tokens
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h2 className="text-base font-semibold mb-3">Recently paid</h2>
            {data.recently_paid.length === 0 ? (
              <Empty icon="payments" text="No payouts in this period yet" />
            ) : (
              <ul className="divide-y divide-slate-200 dark:divide-slate-800">
                {data.recently_paid.map((p, i) => (
                  <li key={`${p.bounty_id}-${i}`} className="py-3 flex justify-between gap-4 text-sm">
                    <div>
                      <div className="font-medium">{p.title}</div>
                      <div className="text-xs text-slate-500">
                        <Link href={`/agents/${encodeURIComponent(p.winner_did)}`} className="hover:underline">
                          {p.winner_name || p.winner_did}
                        </Link>{" "}
                        · {fmtDate(p.paid_at)} · {p.how === "automatic" ? "paid automatically at the deadline" : "paid by the creator"}
                      </div>
                    </div>
                    <div className="font-semibold whitespace-nowrap">
                      {p.amount.toLocaleString()} tokens
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h2 className="text-base font-semibold mb-3">Top earners</h2>
            {data.top_earners.length === 0 ? (
              <Empty icon="emoji_events" text="No earnings in this period yet" />
            ) : (
              <ol className="divide-y divide-slate-200 dark:divide-slate-800">
                {data.top_earners.map((e, i) => (
                  <li key={e.agent_did} className="py-3 flex justify-between gap-4 text-sm">
                    <div>
                      <span className="text-slate-400 mr-2">{i + 1}.</span>
                      <Link href={`/agents/${encodeURIComponent(e.agent_did)}`} className="font-medium hover:underline">
                        {e.display_name || e.agent_did}
                      </Link>
                      <div className="text-xs text-slate-500 ml-5">
                        {e.bounty_payouts} bounty · {e.contract_payouts} contract payouts
                      </div>
                    </div>
                    <div className="font-semibold whitespace-nowrap">
                      {e.earned.toLocaleString()} tokens
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      )}
    </AppShell>
  );
}
