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

export class AgentXWebSocket {
  private ws: WebSocket | null = null;
  private handlers = new Set<Handler>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private token: string | null = null;

  connect(token: string) {
    this.token = token;
    if (this.ws) {
      this.ws.onclose = null; // prevent reconnect loop during manual reconnect
      this.ws.close();
    }
    this.ws = new WebSocket(`${BASE_WS}/ws?token=${token}`);

    this.ws.onmessage = (e) => {
      try {
        const msg: WsMessage = JSON.parse(e.data as string);
        this.handlers.forEach((h) => h(msg));
      } catch {
        // ignore malformed frames
      }
    };

    this.ws.onclose = () => {
      if (this.token) {
        this.reconnectTimer = setTimeout(() => {
          if (this.token) this.connect(this.token);
        }, 5000);
      }
    };
  }

  subscribe(channel: "feed" | "governance" | "alerts") {
    this.ws?.send(
      JSON.stringify({ action: "subscribe_channel", channel })
    );
  }

  onMessage(handler: Handler) {
    this.handlers.add(handler);
  }

  offMessage(handler: Handler) {
    this.handlers.delete(handler);
  }

  disconnect() {
    this.token = null;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }
}

// Singleton — safe to import in any client component
export const agentXWs = new AgentXWebSocket();
