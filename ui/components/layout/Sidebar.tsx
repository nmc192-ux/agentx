"use client";
/**
 * The app shell's left menu (Layer 1 plan, S2): exactly the items in
 * lib/nav.ts SHELL_MENU_ITEMS. Icons only from `md`, icons and labels from
 * `xl`; below `md` the phone tab bar (MobileBottomNav) takes over.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { getLogs } from "@/lib/logger";
import { LAYER_FLAGS } from "@/lib/flags";
import { visibleItems } from "@/lib/layers";
import { SHELL_MENU_ITEMS, isMenuItemActive } from "@/lib/nav";
import { HEALTH_POLL_MS, pollWhileVisible } from "@/lib/poll";
import { getToken } from "@/lib/auth";
import { UnreadBadge, useShellNav } from "./useShellNav";
import { WS_DOT, WS_LABEL, WS_SIGNED_OUT_HINT, wsStatusFromLogs, type WsStatus } from "@/lib/wsStatus";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Hidden layers (lib/layers.ts) drop out while their flag is off.
const MENU_ITEMS = visibleItems(SHELL_MENU_ITEMS, LAYER_FLAGS);

/** Probes /health and derives WS status from the DevPanel log store. */
function useNetworkStatus() {
  const [api, setApi] = useState<"online" | "offline" | "checking">("checking");
  const [ws, setWs]   = useState<WsStatus>("checking");

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
      setWs(wsStatusFromLogs(getLogs(), getToken() !== null));
    }

    checkWs();
    // checkWs only reads the in-page log; checkApi is a network call.
    const stopApi = pollWhileVisible(checkApi, HEALTH_POLL_MS);
    const t2 = setInterval(checkWs, 3_000);
    return () => { stopApi(); clearInterval(t2); };
  }, []);

  return { api, ws };
}

export function Sidebar() {
  const { pathname, ownProfile, unread } = useShellNav();
  const { api, ws } = useNetworkStatus();

  const apiColor = api === "online" ? "bg-green-500" : api === "offline" ? "bg-red-500" : "bg-yellow-400";
  const wsColor  = WS_DOT[ws];
  const apiLabel = api === "online" ? "API Online" : api === "offline" ? "API Offline" : "API Checking…";
  const wsLabel  = `WS ${WS_LABEL[ws]}`;

  return (
    <aside className="hidden md:flex flex-col w-16 xl:w-60 py-6 sticky top-16 h-[calc(100vh-64px)] overflow-y-auto flex-shrink-0">
      <nav className="space-y-1" aria-label="Main menu">
        {MENU_ITEMS.map((item) => {
          const active = isMenuItemActive(pathname, item.href, ownProfile);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-label={item.label}
              aria-current={active ? "page" : undefined}
              title={item.shortcut ? `${item.label} (${item.shortcut})` : item.label}
              className={`flex items-center justify-center xl:justify-start gap-4 px-3 py-2.5 rounded-full text-base transition-colors ${
                active
                  ? "font-bold text-slate-900 dark:text-slate-100 bg-primary/10"
                  : "font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
            >
              <span className="relative">
                <span className="material-symbols-outlined">{item.icon}</span>
                {item.href === "/notifications" && <UnreadBadge count={unread} />}
              </span>
              <span className="hidden xl:inline">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="hidden xl:block mt-auto pb-8">
        <div className="p-4 bg-slate-100 dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-2">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Network Status
          </p>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${apiColor}`} />
            <span className="text-xs font-medium">{apiLabel}</span>
          </div>
          <div className="flex items-center gap-2" title={ws === "signed_out" ? WS_SIGNED_OUT_HINT : undefined}>
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${wsColor}`} />
            <span className="text-xs font-medium">{wsLabel}</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
