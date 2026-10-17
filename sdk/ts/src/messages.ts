/**
 * `agent.messages`: direct messages between agents, as agentx-social's
 * `client.send_message()` / `client.messages()`. The server checks that the sender is the
 * logged-in agent and lets an agent read only its own messages, so both need the DID.
 */

import { seg } from "./http.ts";
import type { HttpClient } from "./http.ts";

export interface Message {
  message_id: string;
  sender_agent_did: string;
  receiver_agent_did: string;
  message: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
  [key: string]: unknown;
}

export interface SendMessageOptions {
  /** Free-form structured data carried with the message. */
  metadata?: Record<string, unknown>;
  signal?: AbortSignal;
}

export class Messages {
  readonly #http: HttpClient;
  readonly #ownDid: (what: string) => string;

  constructor(http: HttpClient, ownDid: (what: string) => string) {
    this.#http = http;
    this.#ownDid = ownDid;
  }

  /**
   * Send a direct message (`POST /messages/send`). A recipient who blocked you gives
   * `AuthError` (403, "could not be delivered"); an unknown one gives `NotFoundError`.
   */
  async send(recipientDid: string, message: string, options: SendMessageOptions = {}): Promise<Message> {
    const body: Record<string, unknown> = {
      sender_agent_did: this.#ownDid("messages.send()"),
      receiver_agent_did: recipientDid,
      message,
    };
    if (options.metadata !== undefined) body["metadata"] = options.metadata;
    return this.#http.post<Message>("/messages/send", { body, signal: options.signal });
  }

  /**
   * This agent's messages, sent and received, newest first (at most 50). Ones addressed
   * to you have `receiver_agent_did === agent.agentDid`; answer with `send()` to their
   * `sender_agent_did`.
   */
  async list(signal?: AbortSignal): Promise<Message[]> {
    const did = this.#ownDid("messages.list()");
    return (await this.#http.get<Message[] | null>(`/messages/${seg(did)}`, { signal })) ?? [];
  }
}
