/**
 * `agent.wallet`: this agent's token wallet. Routes and bodies as agentx-py's
 * `client.wallet` (`sdk/agentx_sdk/wallet.py`: `get_wallet`, `create_wallet`, `get_balance`).
 *
 * Read and open only. Transfers and stakes are not wrapped yet (use `agent.http`).
 */

import type { HttpClient } from "./http.ts";

export interface Wallet {
  wallet_id: string;
  agent_id: string | null;
  /** Whole tokens. */
  balance: number;
  updated_at: string;
  wallet_type: string;
  [key: string]: unknown;
}

export interface CreateWalletOptions {
  /**
   * Tokens to credit on creation. Default 0. Anything above 0 mints tokens and is
   * FOUNDER-only: the server answers `AuthError` (403) for anyone else.
   */
  initialBalance?: number;
  signal?: AbortSignal;
}

export class WalletApi {
  readonly #http: HttpClient;
  readonly #ownDid: (what: string) => string;

  constructor(http: HttpClient, ownDid: (what: string) => string) {
    this.#http = http;
    this.#ownDid = ownDid;
  }

  /** This agent's wallet. A new agent has none yet: that is `NotFoundError`. */
  get(signal?: AbortSignal): Promise<Wallet> {
    return this.#http.get<Wallet>("/wallets/by-did", {
      query: { agent_did: this.#ownDid("wallet.get()") },
      signal,
    });
  }

  /** Open this agent's wallet. Idempotent: an existing wallet keeps its balance. */
  create(options: CreateWalletOptions = {}): Promise<Wallet> {
    return this.#http.post<Wallet>("/wallets", {
      body: { initial_balance: options.initialBalance ?? 0 },
      signal: options.signal,
    });
  }

  /** This agent's balance in whole tokens. */
  async balance(signal?: AbortSignal): Promise<number> {
    return (await this.get(signal)).balance;
  }
}
