export type LogEvent = {
  timestamp: string; // ISO-8601
  type: string;      // e.g. "TASK_STARTED", "WS_CONNECT", …
  payload?: unknown;
  traceId?: string;  // correlates start → complete/failed for a single request
};

const MAX_LOGS = 200;
let logs: LogEvent[] = [];

/** 8-char random base-36 string — lightweight trace correlation ID */
export function generateTraceId(): string {
  return Math.random().toString(36).slice(2, 10);
}

export function logEvent(type: string, payload?: unknown, traceId?: string): void {
  const entry: LogEvent = {
    timestamp: new Date().toISOString(),
    type,
    payload,
    ...(traceId !== undefined && { traceId }),
  };
  logs.push(entry);
  if (logs.length > MAX_LOGS) logs.shift(); // FIFO trim

  // Truncate large payloads in console to prevent browser slowdown
  const display =
    payload && typeof payload === "object"
      ? JSON.stringify(payload).slice(0, 200)
      : (payload ?? "");
  const traceTag = traceId ? ` [${traceId}]` : "";
  console.log(`[AgentX]${traceTag} ${type}`, display);
}

export function getLogs(): LogEvent[] {
  return [...logs]; // return copy — prevents external mutation of internal store
}

export function clearLogs(): void {
  logs = [];
}
