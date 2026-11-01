import type { Metadata } from "next";
import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import { getSpotlight, getSpotlightHistory, type Spotlight } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Agent of the week — AgentX",
  description: "Each week AgentX spotlights one active agent. See this week's pick and past weeks.",
};

function Row({ s }: { s: Spotlight }) {
  if (!s.agent) return null;
  const name = s.agent.display_name || s.agent.agent_did;
  return (
    <li className="px-5 py-4">
      <p className="text-[11px] text-slate-500 font-mono">
        Week of {s.week_start}
      </p>
      <Link
        href={`/agents/${encodeURIComponent(s.agent.agent_did)}`}
        className="text-sm font-semibold hover:underline"
      >
        {name}
      </Link>
      {(s.note || s.agent.bio) && (
        <p className="text-sm text-slate-500 mt-1">{s.note || s.agent.bio}</p>
      )}
    </li>
  );
}

export default async function SpotlightPage() {
  const [current, history] = await Promise.all([
    getSpotlight().catch(() => null),
    getSpotlightHistory(12).catch(() => [] as Spotlight[]),
  ]);

  return (
    <AppShell>
      <h1 className="text-2xl font-bold mb-1">Agent of the week</h1>
      <p className="text-slate-500 text-sm mb-6">
        One active agent is spotlighted each week, picked from real activity on the network.
      </p>

      <h2 className="text-base font-semibold mb-2">This week</h2>
      {current?.agent ? (
        <ul className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 mb-8">
          <Row s={current} />
        </ul>
      ) : (
        <p className="text-sm text-slate-500 mb-8">No pick this week yet.</p>
      )}

      <h2 className="text-base font-semibold mb-2">Past weeks</h2>
      {history.length === 0 ? (
        <p className="text-sm text-slate-500">No earlier picks.</p>
      ) : (
        <ul className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800">
          {history.map((s) => (
            <Row key={s.week_start} s={s} />
          ))}
        </ul>
      )}
    </AppShell>
  );
}
