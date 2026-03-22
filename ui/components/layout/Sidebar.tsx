"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getLogs } from "@/lib/logger";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SIDEBAR_ITEMS = [
  { href: "/dashboard", icon: "dashboard",   label: "Operations"   },
  { href: "/agents",    icon: "smart_toy",   label: "Agents"       },
  { href: "/map",       icon: "hub",         label: "Network Map"  },
  { href: "/developer", icon: "code",        label: "Developer"    },
];

/** Probes /health and derives WS status from the DevPanel log store. */
function useNetworkStatus() {
  const [api, setApi] = useState<"online" | "offline" | "checking">("checking");
  const [ws, setWs]   = useState<"connected" | "disconnected" | "checking">("checking");

  useEffect(() => {
    async function checkApi() {
      try {
        const r = await fetch(`${BASE}/health`, {
          cache: "no-store",
          signal: AbortSignal.timeout(3_000),
        });
        setApi(r.ok ? "online" : "offline");
      } catch {
        setApi("offline");
      }
    }

    function checkWs() {
      const logs = getLogs();
      const wsLogs = logs.filter((l) => l.type.startsWith("WS_"));
      if (!wsLogs.length) { setWs("checking"); return; }
      const last = wsLogs[wsLogs.length - 1];
      if (last.type === "WS_CONNECTED") setWs("connected");
      else if (last.type === "WS_DISCONNECT" || last.type === "WS_ERROR") setWs("disconnected");
      else setWs("checking");
    }

    checkApi();
    checkWs();
    const t1 = setInterval(checkApi,  30_000);
    const t2 = setInterval(checkWs,   3_000);
    return () => { clearInterval(t1); clearInterval(t2); };
  }, []);

  return { api, ws };
}

export function Sidebar() {
  const pathname = usePathname();
  const { api, ws } = useNetworkStatus();

  const apiColor = api === "online" ? "bg-green-500" : api === "offline" ? "bg-red-500" : "bg-yellow-400";
  const wsColor  = ws  === "connected" ? "bg-green-500" : ws === "disconnected" ? "bg-red-500" : "bg-yellow-400";
  const apiLabel = api === "online" ? "API Online" : api === "offline" ? "API Offline" : "API Checking…";
  const wsLabel  = ws  === "connected" ? "WS Connected" : ws === "disconnected" ? "WS Disconnected" : "WS Checking…";

  return (
    <aside className="hidden lg:flex flex-col w-64 py-8 sticky top-16 h-[calc(100vh-64px)] overflow-y-auto flex-shrink-0">
      <div className="space-y-1">
        {SIDEBAR_ITEMS.map((item) => {
          const active = pathname === item.href || (item.href === "/dashboard" && pathname === "/dashboard");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                active
                  ? "text-primary bg-primary/10"
                  : "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
            >
              <span className="material-symbols-outlined">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </div>

      <div className="mt-auto pb-8">
        <div className="p-4 bg-slate-100 dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-2">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Network Status
          </p>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${apiColor}`} />
            <span className="text-xs font-medium">{apiLabel}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${wsColor}`} />
            <span className="text-xs font-medium">{wsLabel}</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
