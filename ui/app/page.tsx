import { ActivityFeed } from "@/components/ActivityFeed";
import { AgentCard } from "@/components/AgentCard";
import { ServiceList } from "@/components/ServiceList";
import { TaskTable } from "@/components/TaskTable";

export default function Home() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(34,211,238,0.18),_transparent_32%),radial-gradient(circle_at_top_right,_rgba(250,204,21,0.14),_transparent_28%),linear-gradient(160deg,_#08111f_0%,_#0f172a_48%,_#111827_100%)] px-4 py-8 text-slate-100 sm:px-6 lg:px-10">
      <div className="mx-auto max-w-7xl">
        <header className="mb-8 rounded-[2rem] border border-white/10 bg-slate-950/45 px-6 py-8 shadow-2xl shadow-cyan-950/20 backdrop-blur">
          <p className="text-xs uppercase tracking-[0.35em] text-cyan-300">
            AgentX Network Ops
          </p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight text-white sm:text-5xl">
            AgentX Control Center
          </h1>
          <p className="mt-4 max-w-3xl text-sm leading-7 text-slate-300 sm:text-base">
            Monitor live activity, agent reputation, task execution, and the
            service marketplace from a single real-time dashboard.
          </p>
        </header>

        <div className="grid gap-6 lg:grid-cols-2 2xl:grid-cols-4">
          <ActivityFeed />
          <AgentCard />
          <TaskTable />
          <ServiceList />
        </div>
      </div>
    </main>
  );
}
