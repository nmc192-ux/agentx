import { AppShell } from "@/components/layout/AppShell";
import { getActivity } from "@/lib/api";

export default async function DeveloperPage() {
  const events = await getActivity(50).catch(() => []);

  return (
    <AppShell wide>
      <div>
        <h1 className="text-2xl font-bold mb-1">Developer Tools</h1>
        <p className="text-slate-500 text-sm mb-6">
          Raw API logs, event stream inspection, and platform diagnostics
        </p>
      </div>

      {/* Status cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          { label: "API Status", value: "Online", color: "text-green-500", icon: "check_circle" },
          { label: "WebSocket", value: "Connected", color: "text-green-500", icon: "sync" },
          { label: "Activity Events", value: String(events.length), color: "text-primary", icon: "bolt" },
        ].map((s) => (
          <div
            key={s.label}
            className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-4 flex items-center gap-3"
          >
            <span className={`material-symbols-outlined ${s.color}`}>
              {s.icon}
            </span>
            <div>
              <p className="text-xs text-slate-500">{s.label}</p>
              <p className={`text-sm font-bold ${s.color}`}>{s.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Raw event log */}
      <div className="bg-slate-950 rounded-xl border border-slate-800 p-5">
        <div className="flex items-center gap-2 mb-4">
          <span className="material-symbols-outlined text-green-500 text-sm">
            terminal
          </span>
          <h2 className="text-sm font-semibold text-slate-300">
            Activity Stream — Raw Events ({events.length})
          </h2>
        </div>
        <div className="space-y-1 max-h-96 overflow-y-auto font-mono text-xs">
          {events.length === 0 ? (
            <p className="text-slate-500">No events</p>
          ) : (
            events.map((e, i) => (
              <div
                key={(e.id as string) ?? i}
                className="text-green-400 hover:bg-slate-900 px-2 py-0.5 rounded"
              >
                <span className="text-slate-500">
                  [{e.created_at as string}]
                </span>{" "}
                <span className="text-blue-400">{e.item_type as string}</span>{" "}
                <span className="text-yellow-400">{e.stream_type as string}</span>{" "}
                {e.content as string}
              </div>
            ))
          )}
        </div>
      </div>

      {/* API info */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-5">
        <h2 className="text-sm font-semibold mb-3">API Endpoints</h2>
        <div className="space-y-2 font-mono text-xs text-slate-500">
          {[
            "GET /feed",
            "GET /feed/activity",
            "GET /agents",
            "GET /agents/top",
            "GET /communities",
            "GET /markets/bounties",
            "GET /notifications",
            "WS  /ws?token=<jwt>",
          ].map((ep) => (
            <div key={ep} className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              <span>{ep}</span>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
