"use client";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { getLogs } from "@/lib/logger";
import { FEED_POLL_MS, HEALTH_POLL_MS, pollWhileVisible } from "@/lib/poll";
import { getToken } from "@/lib/auth";
import { WS_LABEL, WS_TEXT, wsStatusFromLogs, type WsStatus } from "@/lib/wsStatus";

export const dynamic = "force-dynamic";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type ApiStatus = "checking" | "online" | "offline";

function useApiStatus(): ApiStatus {
  const [status, setStatus] = useState<ApiStatus>("checking");
  useEffect(() => {
    async function check() {
      try {
        const r = await fetch(`${BASE}/health`, {
          cache: "no-store",
          signal: AbortSignal.timeout(3_000),
        });
        setStatus(r.ok ? "online" : "offline");
      } catch {
        setStatus("offline");
      }
    }
    return pollWhileVisible(check, HEALTH_POLL_MS);
  }, []);
  return status;
}

function useWsStatus(): WsStatus {
  const [status, setStatus] = useState<WsStatus>("checking");
  useEffect(() => {
    const check = () => setStatus(wsStatusFromLogs(getLogs(), getToken() !== null));
    check();
    const t = setInterval(check, 2_000);
    return () => clearInterval(t);
  }, []);
  return status;
}

export default function DeveloperPage() {
  const apiStatus = useApiStatus();
  const wsStatus  = useWsStatus();
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    async function fetchEvents() {
      try {
        const r = await fetch(`${BASE}/feed/activity?limit=50`, { cache: "no-store" });
        if (r.ok) {
          const data = await r.json();
          setEvents(Array.isArray(data) ? data : []);
        }
      } catch { /* non-fatal */ }
    }
    return pollWhileVisible(fetchEvents, FEED_POLL_MS);
  }, []);

  const apiColor = apiStatus === "online" ? "text-green-500" : apiStatus === "offline" ? "text-red-500" : "text-yellow-400";
  const wsColor  = WS_TEXT[wsStatus];
  const apiLabel = apiStatus === "online" ? "Online" : apiStatus === "offline" ? "Offline" : "Checking…";
  const wsLabel  = WS_LABEL[wsStatus];

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
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-4 flex items-center gap-3">
          <span className={`material-symbols-outlined ${apiColor}`}>check_circle</span>
          <div>
            <p className="text-xs text-slate-500">API Status</p>
            <p className={`text-sm font-bold ${apiColor}`}>{apiLabel}</p>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-4 flex items-center gap-3">
          <span className={`material-symbols-outlined ${wsColor}`}>sync</span>
          <div>
            <p className="text-xs text-slate-500">WebSocket</p>
            <p className={`text-sm font-bold ${wsColor}`}>{wsLabel}</p>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-4 flex items-center gap-3">
          <span className="material-symbols-outlined text-primary">bolt</span>
          <div>
            <p className="text-xs text-slate-500">Activity Events</p>
            <p className="text-sm font-bold text-primary">{events.length}</p>
          </div>
        </div>
      </div>

      {/* Raw event log */}
      <div className="bg-slate-950 rounded-xl border border-slate-800 p-5">
        <div className="flex items-center gap-2 mb-4">
          <span className="material-symbols-outlined text-green-500 text-sm">terminal</span>
          <h2 className="text-sm font-semibold text-slate-300">
            Activity Stream — Raw Events ({events.length})
          </h2>
        </div>
        <div className="space-y-1 max-h-96 overflow-y-auto font-mono text-xs">
          {events.length === 0 ? (
            <p className="text-slate-500">No events — waiting for backend…</p>
          ) : (
            events.map((e, i) => (
              <div
                key={(e.id as string) ?? i}
                className="text-green-400 hover:bg-slate-900 px-2 py-0.5 rounded"
              >
                <span className="text-slate-500">[{e.created_at as string}]</span>{" "}
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
              <span className={`w-2 h-2 rounded-full ${apiStatus === "online" ? "bg-green-500" : "bg-red-500"}`} />
              <span>{ep}</span>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
