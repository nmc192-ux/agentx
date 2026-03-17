export type LogEvent = {
  timestamp: string; // ISO-8601
  type: string;      // e.g. "WS_CONNECT", "API_REQUEST", …
  payload?: unknown;
};

const MAX_LOGS = 200;
let logs: LogEvent[] = [];

export function logEvent(type: string, payload?: unknown): void {
  const entry: LogEvent = {
    timestamp: new Date().toISOString(),
    type,
    payload,
  };
  logs.push(entry);
  if (logs.length > MAX_LOGS) logs.shift(); // FIFO trim

  // Truncate large payloads in console to prevent browser slowdown
  const display =
    payload && typeof payload === "object"
      ? JSON.stringify(payload).slice(0, 200)
      : (payload ?? "");
  console.log(`[AgentX] ${type}`, display);
}

export function getLogs(): LogEvent[] {
  return [...logs]; // return copy — prevents external mutation of internal store
}

export function clearLogs(): void {
  logs = [];
}
