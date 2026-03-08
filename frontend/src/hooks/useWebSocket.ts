/**
 * AgentX — useWebSocket Hook
 * ══════════════════════════
 * Manages a WebSocket connection to the AgentX real-time feed.
 * Handles reconnection, heartbeat, and message dispatch.
 *
 * Usage:
 *   const { status, lastMessage, send } = useWebSocket({
 *     url: process.env.NEXT_PUBLIC_WS_URL!,
 *     token: session.accessToken,
 *     onMessage: (msg) => console.log(msg),
 *   });
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WsMessage, WsStatus } from "@/types";

interface UseWebSocketOptions {
  url:        string;
  token:      string | undefined;
  onMessage?: (message: WsMessage) => void;
  onOpen?:    () => void;
  onClose?:   () => void;
  onError?:   (event: Event) => void;
  /** Automatically reconnect on close. Default: true */
  reconnect?: boolean;
  /** Max reconnect attempts before giving up. Default: 5 */
  maxRetries?: number;
  /** Base backoff delay in ms. Default: 1000 */
  retryDelay?: number;
}

interface UseWebSocketReturn {
  status:      WsStatus;
  lastMessage: WsMessage | null;
  send:        (message: object) => void;
  disconnect:  () => void;
}

export function useWebSocket({
  url,
  token,
  onMessage,
  onOpen,
  onClose,
  onError,
  reconnect  = true,
  maxRetries = 5,
  retryDelay = 1_000,
}: UseWebSocketOptions): UseWebSocketReturn {
  const [status,      setStatus]      = useState<WsStatus>("closed");
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);

  const wsRef        = useRef<WebSocket | null>(null);
  const retriesRef   = useRef(0);
  const timeoutRef   = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef   = useRef(true);

  const clearRetryTimeout = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  };

  const connect = useCallback(() => {
    if (!url || !token) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    // Append JWT as query param (WS can't send Authorization headers)
    const fullUrl = `${url}?token=${encodeURIComponent(token)}`;

    setStatus("connecting");
    const ws = new WebSocket(fullUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      retriesRef.current = 0;
      setStatus("open");
      onOpen?.();
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      try {
        const msg: WsMessage = JSON.parse(event.data as string);
        setLastMessage(msg);
        // Ignore heartbeat messages for onMessage handler to reduce noise
        if (msg.type !== "HEARTBEAT") onMessage?.(msg);
      } catch {
        // malformed message — ignore
      }
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setStatus("closed");
      onClose?.();

      if (reconnect && retriesRef.current < maxRetries) {
        const delay = retryDelay * Math.pow(2, retriesRef.current);
        retriesRef.current += 1;
        timeoutRef.current = setTimeout(connect, delay);
      }
    };

    ws.onerror = (event: Event) => {
      if (!mountedRef.current) return;
      setStatus("error");
      onError?.(event);
    };
  }, [url, token, onMessage, onOpen, onClose, onError, reconnect, maxRetries, retryDelay]);

  // Connect on mount / when token changes
  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      clearRetryTimeout();
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((message: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  const disconnect = useCallback(() => {
    clearRetryTimeout();
    wsRef.current?.close();
    setStatus("closed");
  }, []);

  return { status, lastMessage, send, disconnect };
}
