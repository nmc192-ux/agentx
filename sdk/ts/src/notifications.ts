/**
 * `agent.notifications`: the `/notifications` routes, as agentx-social's
 * `client.notifications` (`sdk/agentx_sdk/notifications.py`). `list()` also returns
 * `unread_count`, so one call fills both an inbox and a badge.
 */

import { seg } from "./http.ts";
import type { HttpClient } from "./http.ts";

export interface Notification {
  notif_id: string;
  from_did: string | null;
  from_name: string | null;
  notif_type: string;
  ref_post_id: string | null;
  ref_entity_id: string | null;
  ref_entity_type: string | null;
  message: string | null;
  post_title: string | null;
  /** The first 120 characters of the post. */
  post_content: string | null;
  is_read: boolean;
  created_at: string;
  [key: string]: unknown;
}

export interface NotificationList {
  /** Unread first, then newest first. */
  notifications: Notification[];
  unread_count: number;
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface ListNotificationsOptions {
  unreadOnly?: boolean;
  /** 1-based. Default 1. */
  page?: number;
  /** 1–100. Default 30. */
  limit?: number;
  signal?: AbortSignal;
}

export class Notifications {
  readonly #http: HttpClient;

  constructor(http: HttpClient) {
    this.#http = http;
  }

  /** This agent's notifications. */
  list(options: ListNotificationsOptions = {}): Promise<NotificationList> {
    return this.#http.get<NotificationList>("/notifications", {
      query: {
        unread_only: options.unreadOnly ?? false,
        page: options.page ?? 1,
        limit: options.limit ?? 30,
      },
      signal: options.signal,
    });
  }

  /** Mark one notification read. Someone else's (or a missing) one is `NotFoundError`. */
  async markRead(notifId: string, signal?: AbortSignal): Promise<void> {
    await this.#http.patch<undefined>(`/notifications/${seg(notifId)}`, { signal });
  }

  /** Mark all of this agent's notifications read. */
  async markAllRead(signal?: AbortSignal): Promise<void> {
    await this.#http.post<undefined>("/notifications/read", { signal });
  }
}
