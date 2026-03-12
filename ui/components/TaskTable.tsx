"use client";

import { useEffect, useState } from "react";

const API_BASE = "http://localhost:8000";
const REFRESH_MS = 3000;

type TaskItem = {
  task_id: string;
  executor_agent_did: string;
  status: string;
  task_type: string;
};

type TaskResponse = {
  recent_tasks: TaskItem[];
  status_counts: Record<string, number>;
};

async function fetchTasks(): Promise<TaskResponse> {
  const response = await fetch(`${API_BASE}/dashboard/tasks`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch tasks");
  }

  return response.json();
}

export function TaskTable() {
  const [data, setData] = useState<TaskResponse>({
    recent_tasks: [],
    status_counts: {},
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const load = async () => {
      try {
        const nextData = await fetchTasks();
        if (!active) {
          return;
        }
        setData(nextData);
        setError(null);
      } catch {
        if (!active) {
          return;
        }
        setError("Task monitor unavailable");
      }
    };

    void load();
    const timer = window.setInterval(() => {
      void load();
    }, REFRESH_MS);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">Execution Grid</p>
          <h2 className="panel-title">Tasks</h2>
        </div>
        <div className="flex gap-2">
          {Object.entries(data.status_counts)
            .slice(0, 3)
            .map(([status, count]) => (
              <span key={status} className="status-chip">
                {status}: {count}
              </span>
            ))}
        </div>
      </div>

      {error ? <p className="panel-empty">{error}</p> : null}

      <div className="overflow-auto rounded-2xl border border-white/10">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-white/5 text-xs uppercase tracking-[0.2em] text-slate-400">
            <tr>
              <th className="px-4 py-3 font-medium">Task ID</th>
              <th className="px-4 py-3 font-medium">Executor</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Type</th>
            </tr>
          </thead>
          <tbody>
            {data.recent_tasks.slice(0, 10).map((task) => (
              <tr key={task.task_id} className="border-t border-white/10 text-slate-200">
                <td className="px-4 py-3 font-mono text-xs">
                  {task.task_id.slice(0, 8)}...
                </td>
                <td className="px-4 py-3 text-xs">{task.executor_agent_did}</td>
                <td className="px-4 py-3">
                  <span className="rounded-full bg-cyan-400/15 px-3 py-1 text-xs font-semibold text-cyan-200">
                    {task.status}
                  </span>
                </td>
                <td className="px-4 py-3">{task.task_type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!error && data.recent_tasks.length === 0 ? (
        <p className="panel-empty">No tasks available</p>
      ) : null}
    </section>
  );
}
