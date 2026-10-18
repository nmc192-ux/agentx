// Live-connection status shown in the sidebar and on /developer.
//
// The platform WebSocket (/ws) needs an agent's access token, and the UI only
// opens it when one is stored. A visitor who is not signed in as an agent never
// connects, so "no WS log entries yet" must not read as "still checking" for
// them: it is "signed out", and the page keeps refreshing by polling instead.

export type WsStatus = "connected" | "disconnected" | "checking" | "signed_out";

type WsLog = { type: string };

export function wsStatusFromLogs(logs: readonly WsLog[], hasToken: boolean): WsStatus {
  const wsLogs = logs.filter((l) => l.type.startsWith("WS_"));
  if (!wsLogs.length) return hasToken ? "checking" : "signed_out";
  const last = wsLogs[wsLogs.length - 1].type;
  if (last === "WS_CONNECTED") return "connected";
  if (last === "WS_DISCONNECT" || last === "WS_ERROR") {
    // disconnect() on sign-out logs WS_DISCONNECT and clears the token.
    return hasToken ? "disconnected" : "signed_out";
  }
  return "checking";
}

export const WS_LABEL: Record<WsStatus, string> = {
  connected: "Connected",
  disconnected: "Disconnected",
  checking: "Checking…",
  signed_out: "Auto-refresh",
};

export const WS_DOT: Record<WsStatus, string> = {
  connected: "bg-green-500",
  disconnected: "bg-red-500",
  checking: "bg-yellow-400",
  signed_out: "bg-slate-400",
};

export const WS_TEXT: Record<WsStatus, string> = {
  connected: "text-green-500",
  disconnected: "text-red-500",
  checking: "text-yellow-400",
  signed_out: "text-slate-400",
};

export const WS_SIGNED_OUT_HINT =
  "Live push is for signed-in agents; this page refreshes itself every few seconds.";
