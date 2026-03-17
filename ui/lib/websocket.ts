import { logEvent } from "./logger";

export type WsMessage =
  | { type: "CONNECTED"; agent_did: string; ts: string }
  | { type: "HEARTBEAT"; ts: string }
  | { type: "NEW_POST"; data: Record<string, unknown> }
  | { type: "TRUST_UPDATE"; data: Record<string, unknown> }
  | { type: string; data?: unknown };

type Handler = (msg: WsMessage) => void;

const BASE_WS = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/^http/, "ws");

const BASE_DELAY = 1_000;  // 1 s
const MAX_DELAY  = 30_000; // 30 s

export class AgentXWebSocket {
  private ws: WebSocket | null = null;
  private handlers = new Set<Handler>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private token: string | null = null;

  private reconnectAttempts = 0;
  private pendingSubscriptions: string[] = [];
  private isConnecting = false;
  private activeSubscriptions = new Set<string>();

  connect(token: string) {
    if (this.isConnecting) return; // already mid-handshake
    this.isConnecting = true;
    this.token = token;

    if (this.ws) {
      this.ws.onclose = null; // suppress reconnect loop on manual call
      this.ws.close();
    }

    const attempt = this.reconnectAttempts;
    if (attempt === 0) {
      logEvent("WS_CONNECT", { token: "[redacted]" });
    } else {
      logEvent("WS_RECONNECT", {
        attempt,
        delay: Math.min(BASE_DELAY * 2 ** attempt, MAX_DELAY),
      });
    }

    this.ws = new WebSocket(`${BASE_WS}/ws?token=${token}`);

    // ── open: reset counters, re-subscribe all active channels ──────────
    this.ws.onopen = () => {
      this.isConnecting = false;
      this.reconnectAttempts = 0;
      logEvent("WS_CONNECTED");

      // Re-send ALL previously subscribed channels (handles reconnect state recovery)
      for (const channel of this.activeSubscriptions) {
        this.ws!.send(JSON.stringify({ action: "subscribe_channel", channel }));
      }

      // Clear the pending queue — already covered by activeSubscriptions replay
      this.pendingSubscriptions = [];
    };

    // ── message ──────────────────────────────────────────────────────────
    this.ws.onmessage = (e) => {
      try {
        const msg: WsMessage = JSON.parse(e.data as string);
        logEvent("WS_MESSAGE", { type: msg.type });
        this.handlers.forEach((h) => h(msg));
      } catch (err) {
        logEvent("WS_ERROR", { reason: "malformed frame", raw: e.data });
        void err; // suppress unused variable warning
      }
    };

    // ── close: exponential backoff reconnect ─────────────────────────────
    this.ws.onclose = () => {
      this.isConnecting = false;
      if (!this.token) return; // disconnected intentionally

      const delay = Math.min(BASE_DELAY * 2 ** this.reconnectAttempts, MAX_DELAY);
      logEvent("WS_DISCONNECT", { delay });
      this.reconnectAttempts++;

      if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
      this.reconnectTimer = setTimeout(() => {
        if (this.token) this.connect(this.token);
      }, delay);
    };
  }

  subscribe(channel: string) {
    // Always record — ensures re-subscription after any future reconnect
    this.activeSubscriptions.add(channel);

    if (this.ws?.readyState === WebSocket.OPEN) {
      // Already open — send immediately
      this.ws.send(JSON.stringify({ action: "subscribe_channel", channel }));
    } else {
      // Queue for flush on next open; prevent duplicates
      if (!this.pendingSubscriptions.includes(channel)) {
        this.pendingSubscriptions.push(channel);
      }
    }
  }

  onMessage(handler: Handler) {
    this.handlers.add(handler);
  }

  offMessage(handler: Handler) {
    this.handlers.delete(handler);
  }

  disconnect() {
    logEvent("WS_DISCONNECT", { delay: 0 });
    this.token = null;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.pendingSubscriptions = [];
    this.activeSubscriptions.clear();
    this.reconnectAttempts = 0;
    this.isConnecting = false;
    this.ws?.close();
    this.ws = null;
  }
}

// Singleton — safe to import in any client component
export const agentXWs = new AgentXWebSocket();
