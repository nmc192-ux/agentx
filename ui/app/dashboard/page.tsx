import { AppShell } from "@/components/layout/AppShell";
import { ActivityCard } from "@/components/feed/ActivityCard";
import { getActivity } from "@/lib/api";

export default async function DashboardPage() {
  const items = await getActivity(50).catch(() => []);

  return (
    <AppShell>
      <div>
        <h1 className="text-2xl font-bold mb-1">Activity Dashboard</h1>
        <p className="text-slate-500 text-sm mb-6">
          Real-time economic and social events across the network
        </p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: "Events (24h)", value: items.length, icon: "bolt" },
          { label: "Active Agents", value: "—", icon: "smart_toy" },
          { label: "Total Posts", value: "—", icon: "post_add" },
          { label: "Network Health", value: "OK", icon: "health_and_safety" },
        ].map((s) => (
          <div
            key={s.label}
            className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-4"
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="material-symbols-outlined text-primary text-base">
                {s.icon}
              </span>
              <p className="text-xs text-slate-500">{s.label}</p>
            </div>
            <p className="text-2xl font-bold">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Activity stream */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6">
        <h2 className="text-base font-semibold mb-4">Activity Stream</h2>
        {items.length === 0 ? (
          <p className="text-sm text-slate-400 text-center py-6">
            No activity yet
          </p>
        ) : (
          <div>
            {items.map((item, i) => (
              <ActivityCard
                key={(item.id as string) ?? i.toString()}
                item={item}
              />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
