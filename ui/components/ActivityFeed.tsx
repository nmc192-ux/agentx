"use client";

import { useEffect, useRef, useState } from "react";

const API_BASE = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/events/stream";

type ActivityItem = {
  event_id: string;
  event_type: string;
  agent_did: string;
  timestamp: string;
  payload: Record<string, unknown>;
};

async function fetchActivity(): Promise<ActivityItem[]> {
  const response = await fetch(`${API_BASE}/dashboard/activity`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error("Failed to fetch activity");
  }

  return response.json();
}

function formatTimestamp(value: string) {
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatEvent(value: string) {
  return value.replace(/_/g, " ");
}

function summarizePayload(item: ActivityItem) {
  const payload = item.payload || {};

  if (typeof payload.message === "string") {
    return payload.message;
  }
  if (typeof payload.title === "string") {
    return payload.title;
  }
  if (typeof payload.topic === "string") {
    return payload.topic;
  }
  if (typeof payload.task_type === "string") {
    return payload.task_type;
  }
  if (typeof payload.workflow_type === "string") {
    return payload.workflow_type;
  }

  return formatEvent(item.event_type);
}

export function ActivityFeed() {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const eventIds = useRef(new Set<string>());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let websocket: WebSocket | null = null;
    let reconnectTimer: number | null = null;

    const load = async () => {
      try {
        const nextItems = await fetchActivity();
        const newItems: ActivityItem[] = [];
        for (const event of nextItems) {
          if (!event.event_id) {
            continue;
          }
          if (!eventIds.current.has(event.event_id)) {
            eventIds.current.add(event.event_id);
            newItems.push(event);
          }
        }
        setItems((current) => [...newItems, ...current].slice(0, 50));
        setError(null);
      } catch {
        setError("Activity feed unavailable");
      }
    };

    const connect = () => {
      websocket = new WebSocket(WS_URL);

      websocket.onopen = () => {
        setError(null);
      };

      websocket.onmessage = (event) => {
        try {
          const nextItem = JSON.parse(event.data) as ActivityItem;
          if (!nextItem.event_type || !nextItem.event_id) {
            return;
          }
          setItems((current) => {
            if (eventIds.current.has(nextItem.event_id)) {
              return current;
            }
            eventIds.current.add(nextItem.event_id);
            return [nextItem, ...current].slice(0, 50);
          });
        } catch {
          setError("Invalid event payload received");
        }
      };

      websocket.onerror = () => {
        setError("Event stream unavailable");
      };

      websocket.onclose = () => {
        reconnectTimer = window.setTimeout(connect, 3000);
      };
    };

    void load();
    connect();

    return () => {
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      websocket?.close();
    };
  }, []);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">Live Stream</p>
          <h2 className="panel-title">Activity Feed</h2>
        </div>
        <span className="status-chip">WebSocket</span>
      </div>

      {error ? <p className="panel-empty">{error}</p> : null}

      <div className="space-y-3 overflow-y-auto pr-1">
        {items.slice(0, 12).map((item, index) => (
          <article
            key={item.event_id || `${item.event_id}-${index}`}
            className="rounded-2xl border border-white/10 bg-white/5 p-4"
          >
            <div className="mb-2 flex items-center justify-between gap-3 text-xs uppercase tracking-[0.2em] text-slate-400">
              <span>{formatTimestamp(item.timestamp)}</span>
              <span>{formatEvent(item.event_type)}</span>
            </div>
            <p className="text-sm font-medium text-slate-100">
              {summarizePayload(item)}
            </p>
            <p className="mt-2 text-xs text-slate-400">{item.agent_did}</p>
          </article>
        ))}

        {!error && items.length === 0 ? (
          <p className="panel-empty">No recent activity</p>
        ) : null}
      </div>
    </section>
  );
}
