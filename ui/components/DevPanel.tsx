"use client";

import { useEffect, useRef, useState } from "react";
import { clearLogs, getLogs, type LogEvent } from "@/lib/logger";

const TYPE_COLOR: Record<string, string> = {
  WS_CONNECT:    "#58a6ff",
  WS_RECONNECT:  "#d29922",
  WS_CONNECTED:  "#3fb950",
  WS_MESSAGE:    "#79c0ff",
  WS_DISCONNECT: "#f85149",
  WS_ERROR:      "#ff7b72",
  API_REQUEST:   "#e6edf3",
  API_RESPONSE:  "#3fb950",
  API_ERROR:     "#f85149",
};

function fmt(ts: string): string {
  // Extract HH:MM:SS from ISO-8601 timestamp
  return ts.slice(11, 19);
}

function fmtPayload(payload: unknown): string {
  if (payload === undefined || payload === null || payload === "") return "";
  const raw =
    typeof payload === "object"
      ? JSON.stringify(payload)
      : String(payload);
  return raw.length > 100 ? raw.slice(0, 97) + "…" : raw;
}

export default function DevPanel() {
  // ── dev-only gate — evaluated at module level so it tree-shakes cleanly ──
  if (process.env.NODE_ENV === "production") return null;

  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [paused, setPaused] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Single interval — recreated (with cleanup) whenever paused toggles.
  // Guarantees exactly one timer exists at any point; clears on unmount.
  useEffect(() => {
    const interval = setInterval(() => {
      if (!paused) {
        setLogs(getLogs());
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [paused]);

  // Auto-scroll to bottom on new entries (when not paused)
  useEffect(() => {
    if (!paused) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, paused]);

  const handleClear = () => {
    clearLogs();
    setLogs([]);
  };

  return (
    <div
      style={{
        position:     "fixed",
        bottom:       16,
        right:        16,
        width:        360,
        height:       320,
        background:   "#111",
        border:       "1px solid #333",
        borderRadius: 8,
        display:      "flex",
        flexDirection:"column",
        zIndex:       9999,
        fontFamily:   "monospace",
        fontSize:     11,
        boxShadow:    "0 4px 24px rgba(0,0,0,0.6)",
      }}
    >
      {/* ── header bar ─────────────────────────────────────────────────── */}
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

      {/* ── log list ────────────────────────────────────────────────────── */}
      <div
        style={{
          flex:      1,
          overflowY: "auto",
          padding:   "4px 0",
        }}
      >
        {/* Render latest 50 entries from the in-memory store */}
        {logs.slice(-50).length === 0 ? (
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
          logs.slice(-50).map((log, i) => (
            <div
              key={i}
              style={{
                display:    "flex",
                gap:        6,
                padding:    "2px 10px",
                borderBottom: "1px solid #1a1a1a",
                alignItems: "flex-start",
              }}
            >
              {/* time */}
              <span style={{ color: "#555", flexShrink: 0, width: 60 }}>
                {fmt(log.timestamp)}
              </span>

              {/* type */}
              <span
                style={{
                  color:      TYPE_COLOR[log.type] ?? "#e6edf3",
                  fontWeight: "bold",
                  flexShrink: 0,
                  width:      110,
                  overflow:   "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {log.type}
              </span>

              {/* payload */}
              <span
                style={{
                  color:    "#888",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace:   "nowrap",
                }}
              >
                {fmtPayload(log.payload)}
              </span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* ── footer: entry count ──────────────────────────────────────────── */}
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
        {Math.min(logs.length, 50)} / 50 entries shown · {paused ? "paused" : "live"}
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
