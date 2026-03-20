"use client";
import { useEffect, useRef, useState } from "react";
import { agentXWs } from "@/lib/websocket";
import { TaskCard } from "./TaskCard";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const MAX_ITEMS = 100;

export function UnifiedFeed() {
  const [items, setItems] = useState<Record<string, unknown>[]>([]);
  const seenIds = useRef(new Set<string>());
  const containerRef = useRef<HTMLDivElement>(null);
  const userScrolled = useRef(false);

  function merge(incoming: Record<string, unknown>[]) {
    const fresh = incoming.filter((item) => {
      const id = (item.id ?? item.event_id) as string | undefined;
      if (!id) return false;
      if (seenIds.current.has(id)) return false;
      seenIds.current.add(id);
      return true;
    });
    if (!fresh.length) return;
    setItems((prev) => [...fresh, ...prev].slice(0, MAX_ITEMS));
  }

  // Poll /feed/activity every 5 s
  useEffect(() => {
    async function poll() {
      try {
        const r = await fetch(`${BASE}/feed/activity?limit=50`, { cache: "no-store" });
        if (r.ok) {
          const data = await r.json();
          if (Array.isArray(data)) merge(data);
        }
      } catch { /* non-fatal */ }
    }
    poll();
    const t = setInterval(poll, 5_000);
    return () => clearInterval(t);
  }, []);

  // WS listener: prepend NEW_POST events
  useEffect(() => {
    function handler(event: { type: string; data?: unknown }) {
      if (event.type === "NEW_POST") {
        const d = event.data as Record<string, unknown> | undefined;
        const item: Record<string, unknown> = {
          id:          d?.id ?? `ws-${Date.now()}`,
          stream_type: "NEW_POST",
          content:     (d?.title as string) ?? "",
          created_at:  new Date().toISOString(),
        };
        merge([item]);
      }
    }
    agentXWs.onMessage(handler);
    return () => agentXWs.offMessage(handler);
  }, []);

  // Auto-scroll to top when new items arrive, unless user has scrolled down
  useEffect(() => {
    if (!userScrolled.current && containerRef.current) {
      containerRef.current.scrollTop = 0;
    }
  }, [items]);

  function onScroll() {
    if (!containerRef.current) return;
    userScrolled.current = containerRef.current.scrollTop > 40;
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Live Activity</p>
      </div>
      <div
        ref={containerRef}
        onScroll={onScroll}
        className="flex-1 overflow-y-auto"
      >
        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-slate-400">
            <span className="material-symbols-outlined text-3xl animate-pulse">bolt</span>
            <p className="text-sm">Waiting for activity…</p>
          </div>
        ) : (
          items.map((item, i) => (
            <TaskCard
              key={((item.id ?? item.event_id) as string) ?? i}
              item={item}
            />
          ))
        )}
      </div>
    </div>
  );
}
