"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { clearLogs, getLogs, type LogEvent } from "@/lib/logger";

// ── colour map ───────────────────────────────────────────────────────────────
const TYPE_COLOR: Record<string, string> = {
  WS_CONNECT:     "#58a6ff",
  WS_RECONNECT:   "#d29922",
  WS_CONNECTED:   "#3fb950",
  WS_DISCONNECT:  "#f85149",
  WS_ERROR:       "#ff7b72",
  AGENT_EVENT:    "#79c0ff",
  TASK_STARTED:   "#e6edf3",
  TASK_COMPLETED: "#3fb950",
  TASK_FAILED:    "#f85149",
};

// Status of a trace — drives the left-border colour
function traceStatus(events: LogEvent[]): "completed" | "failed" | "running" {
  for (const e of events) {
    if (e.type === "TASK_FAILED")    return "failed";
    if (e.type === "TASK_COMPLETED") return "completed";
  }
  return "running";
}

const TRACE_BORDER: Record<string, string> = {
  completed: "#3fb950",
  failed:    "#f85149",
  running:   "#58a6ff",
};

// ── helpers ───────────────────────────────────────────────────────────────────
function fmt(ts: string): string {
  return ts.slice(11, 19); // HH:MM:SS from ISO-8601
}

function fmtPayload(payload: unknown): string {
  if (payload === undefined || payload === null || payload === "") return "";
  const raw =
    typeof payload === "object" ? JSON.stringify(payload) : String(payload);
  return raw.length > 80 ? raw.slice(0, 77) + "…" : raw;
}

// ── sub-components ────────────────────────────────────────────────────────────

/** A single flat log row (used both in trace expansions and untraced section) */
function LogRow({ log, indent = false }: { log: LogEvent; indent?: boolean }) {
  return (
    <div
      style={{
        display:      "flex",
        gap:          6,
        padding:      indent ? "2px 10px 2px 20px" : "2px 10px",
        borderBottom: "1px solid #1a1a1a",
        alignItems:   "flex-start",
      }}
    >
      <span style={{ color: "#555", flexShrink: 0, width: 60 }}>
        {fmt(log.timestamp)}
      </span>
      <span
        style={{
          color:        TYPE_COLOR[log.type] ?? "#e6edf3",
          fontWeight:   "bold",
          flexShrink:   0,
          width:        110,
          overflow:     "hidden",
          textOverflow: "ellipsis",
          whiteSpace:   "nowrap",
        }}
      >
        {log.type}
      </span>
      <span
        style={{
          color:        "#888",
          overflow:     "hidden",
          textOverflow: "ellipsis",
          whiteSpace:   "nowrap",
          flex:         1,
        }}
      >
        {fmtPayload(log.payload)}
      </span>
    </div>
  );
}

/** A collapsible trace block grouping all events sharing a traceId */
function TraceBlock({
  traceId,
  events,
  expanded,
  onToggle,
}: {
  traceId: string;
  events: LogEvent[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const status = traceStatus(events);
  const borderColor = TRACE_BORDER[status];

  return (
    <div
      style={{
        borderLeft:   `2px solid ${borderColor}`,
        background:   "#161616",
        marginBottom: 2,
      }}
    >
      {/* ── trace header (clickable) ─────────────────────────────────────── */}
      <div
        onClick={onToggle}
        style={{
          display:        "flex",
          alignItems:     "center",
          gap:            6,
          padding:        "3px 10px",
          cursor:         "pointer",
          userSelect:     "none",
          borderBottom:   expanded ? "1px solid #222" : "none",
        }}
      >
        <span style={{ color: "#555", fontSize: 9 }}>
          {expanded ? "▼" : "▶"}
        </span>
        <span style={{ color: borderColor, fontWeight: "bold" }}>
          Trace
        </span>
        <span style={{ color: "#555" }}>[{traceId}]</span>
        <span style={{ color: "#444", marginLeft: "auto", fontSize: 9 }}>
          {events.length} event{events.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* ── expanded events ──────────────────────────────────────────────── */}
      {expanded &&
        events.map((log, i) => <LogRow key={i} log={log} indent />)}
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────────
export default function DevPanel() {
  if (process.env.NODE_ENV === "production") return null;

  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [paused, setPaused] = useState(false);
  const [expandedTraces, setExpandedTraces] = useState<Set<string>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  // Single interval — recreated with cleanup whenever paused toggles
  useEffect(() => {
    const interval = setInterval(() => {
      if (!paused) setLogs(getLogs());
    }, 1000);
    return () => clearInterval(interval);
  }, [paused]);

  // Auto-scroll when not paused
  useEffect(() => {
    if (!paused) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs, paused]);

  // ── derive trace groups from latest 50 logs ───────────────────────────────
  const { traces, untraced } = useMemo(() => {
    const slice = logs.slice(-50);
    const traceMap = new Map<string, LogEvent[]>();
    const untracedList: LogEvent[] = [];

    for (const log of slice) {
      if (log.traceId) {
        const bucket = traceMap.get(log.traceId) ?? [];
        bucket.push(log);
        traceMap.set(log.traceId, bucket);
      } else {
        untracedList.push(log);
      }
    }

    return { traces: traceMap, untraced: untracedList };
  }, [logs]);

  const toggleTrace = (id: string) =>
    setExpandedTraces((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const handleClear = () => {
    clearLogs();
    setLogs([]);
    setExpandedTraces(new Set());
  };

  const total = Math.min(logs.length, 50);

  return (
    <div
      style={{
        position:      "fixed",
        bottom:        16,
        right:         16,
        width:         360,
        height:        320,
        background:    "#111",
        border:        "1px solid #333",
        borderRadius:  8,
        display:       "flex",
        flexDirection: "column",
        zIndex:        9999,
        fontFamily:    "monospace",
        fontSize:      11,
        boxShadow:     "0 4px 24px rgba(0,0,0,0.6)",
      }}
    >
      {/* ── header bar ──────────────────────────────────────────────────── */}
      <div
        style={{
          display:        "flex",
          alignItems:     "center",
          justifyContent: "space-between",
          padding:        "5px 10px",
          borderBottom:   "1px solid #333",
          background:     "#1a1a1a",
          borderRadius:   "8px 8px 0 0",
          flexShrink:     0,
        }}
      >
        <span style={{ color: "#888", fontWeight: "bold", fontSize: 11 }}>
          ⬡ AgentX DevPanel
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            onClick={() => setPaused((p) => !p)}
            style={btnStyle(paused ? "#d29922" : "#3fb950")}
          >
            {paused ? "▶ Resume" : "⏸ Pause"}
          </button>
          <button onClick={handleClear} style={btnStyle("#f85149")}>
            ✕ Clear
          </button>
        </div>
      </div>

      {/* ── scrollable body ─────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "4px 0" }}>
        {total === 0 ? (
          <div
            style={{
              color:     "#555",
              textAlign: "center",
              marginTop: 60,
              fontSize:  12,
            }}
          >
            No logs yet
          </div>
        ) : (
          <>
            {/* ── trace groups (ordered by first-seen traceId) ─────────── */}
            {traces.size > 0 && (
              <div style={{ marginBottom: 4 }}>
                {Array.from(traces.entries()).map(([id, events]) => (
                  <TraceBlock
                    key={id}
                    traceId={id}
                    events={events}
                    expanded={expandedTraces.has(id)}
                    onToggle={() => toggleTrace(id)}
                  />
                ))}
              </div>
            )}

            {/* ── untraced flat rows ───────────────────────────────────── */}
            {untraced.map((log, i) => (
              <LogRow key={`u-${i}`} log={log} />
            ))}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* ── footer ──────────────────────────────────────────────────────── */}
      <div
        style={{
          padding:      "3px 10px",
          borderTop:    "1px solid #333",
          color:        "#555",
          fontSize:     10,
          flexShrink:   0,
          background:   "#1a1a1a",
          borderRadius: "0 0 8px 8px",
        }}
      >
        {total} / 50 entries · {traces.size} trace{traces.size !== 1 ? "s" : ""} · {paused ? "paused" : "live"}
      </div>
    </div>
  );
}

function btnStyle(color: string): React.CSSProperties {
  return {
    background:   "transparent",
    border:       `1px solid ${color}`,
    color,
    borderRadius: 4,
    padding:      "2px 7px",
    fontSize:     10,
    cursor:       "pointer",
    fontFamily:   "monospace",
  };
}
