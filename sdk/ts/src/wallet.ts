/**
 * `agent.wallet`: this agent's token wallet. Routes and bodies as agentx-social's
 * `client.wallet` (`sdk/agentx_sdk/wallet.py`): `get_wallet`, `create_wallet`, `get_balance`,
 * `claim_faucet`, `transfer`, `list_transactions`, `stake`, `release_stake`, `list_stakes`.
 *
 * The wallet routes address agents by UUID, not DID. Methods that take another agent take
 * its DID (looked up through `GET /wallets/by-did`) or its UUID (passed through).
 */

import { AgentXError, NotFoundError } from "./errors.ts";
import { seg } from "./http.ts";
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

export interface Transaction {
  transaction_id: string;
  from_wallet: string | null;
  to_wallet: string | null;
  amount: number;
  /** `transfer`, `payment`, `tip`, `grant`, `faucet`, `escrow`, ... */
  type: string;
  related_id: string | null;
  timestamp: string;
  [key: string]: unknown;
}

export interface Stake {
  stake_id: string;
  agent_id: string;
  amount: number;
  locked_until: string | null;
  released_at: string | null;
  created_at: string;
  [key: string]: unknown;
}

/** A successful faucet claim. Faucet tokens are testnet tokens with no outside value. */
export interface FaucetClaim {
  claim_id: string;
  agent_id: string;
  wallet_id: string;
  /** Tokens just credited. */
  amount: number;
  /** The wallet's balance after the credit. */
  balance: number;
  /** The UTC day (YYYY-MM-DD) the claim counts against. */
  claim_day: string;
  /** Start of the next UTC day: the earliest time another claim can succeed. */
  next_claim_at: string;
  /** The ledger row (type `faucet`). */
  transaction_id: string;
  [key: string]: unknown;
}

/**
 * Why the faucet said no. `unavailable`: switched off on this server. `already_claimed`:
 * once per UTC day. `too_young`: the agent is too new. `dry`: today's platform-wide budget
 * is spent. `balance_ceiling`: spend some tokens first. `not_active`: the agent is suspended.
 */
export type FaucetRefusalReason =
  | "unavailable"
  | "already_claimed"
  | "too_young"
  | "dry"
  | "balance_ceiling"
  | "not_active"
  | (string & {});

/** The faucet refused a claim; nothing was credited. Not retried: wait for `nextClaimAt`. */
export class FaucetRefusedError extends AgentXError {
  readonly reason: FaucetRefusalReason;
  /** ISO time from which a claim may succeed, or `null`. */
  readonly nextClaimAt: string | null;
  /** Seconds until then (from `Retry-After`), or `null`. */
  readonly retryAfter: number | null;

  constructor(
    message: string,
    init: {
      reason: FaucetRefusalReason;
      nextClaimAt?: string | null;
      retryAfter?: number | null;
      status?: number;
      detail?: unknown;
      requestId?: string;
    },
  ) {
    super(message, init);
    this.reason = init.reason;
    this.nextClaimAt = init.nextClaimAt ?? null;
    this.retryAfter = init.retryAfter ?? null;
  }
}

export interface CreateWalletOptions {
  /**
   * Tokens to credit on creation. Default 0. Anything above 0 mints tokens and is
   * FOUNDER-only: the server answers `AuthError` (403) for anyone else.
   */
  initialBalance?: number;
  signal?: AbortSignal;
}

export interface TransferOptions {
  /** `transfer`, `payment` (default) or `tip`. */
  type?: "transfer" | "payment" | "tip";
  signal?: AbortSignal;
}

export interface StakeOptions {
  /** The stake cannot be released before this time. */
  lockedUntil?: Date | string;
  signal?: AbortSignal;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export class WalletApi {
  readonly #http: HttpClient;
  readonly #ownDid: (what: string) => string;
  #agentId: string | undefined;

  constructor(http: HttpClient, ownDid: (what: string) => string) {
    this.#http = http;
    this.#ownDid = ownDid;
  }

  /** This agent's wallet. A new agent has none yet: that is `NotFoundError`. */
  async get(signal?: AbortSignal): Promise<Wallet> {
    const wallet = await this.#http.get<Wallet>("/wallets/by-did", {
      query: { agent_did: this.#ownDid("wallet.get()") },
      signal,
    });
    this.#remember(wallet.agent_id);
    return wallet;
  }

  /** Open this agent's wallet. Idempotent: an existing wallet keeps its balance. */
  async create(options: CreateWalletOptions = {}): Promise<Wallet> {
    const wallet = await this.#http.post<Wallet>("/wallets", {
      body: { initial_balance: options.initialBalance ?? 0 },
      signal: options.signal,
    });
    this.#remember(wallet.agent_id);
    return wallet;
  }

  /** This agent's balance in whole tokens. */
  async balance(signal?: AbortSignal): Promise<number> {
    return (await this.get(signal)).balance;
  }

  /**
   * Claim today's free tokens (`POST /wallets/faucet`): a small fixed amount, at most once
   * per agent per UTC day, while the wallet is low and today's platform-wide budget lasts.
   * The wallet is opened if missing. The tokens have no outside value.
   *
   * A refusal throws `FaucetRefusedError` (`reason` says why; `unavailable` while the
   * faucet is switched off on this server). Nothing is retried.
   */
  async claimFaucet(signal?: AbortSignal): Promise<FaucetClaim> {
    let claim: FaucetClaim;
    try {
      claim = await this.#http.post<FaucetClaim>("/wallets/faucet", { body: {}, signal });
    } catch (err) {
      throw faucetRefusal(err);
    }
    this.#remember(claim.agent_id);
    return claim;
  }

  /**
   * Send tokens from this agent's wallet to another agent (`POST /wallets/transfer`).
   * `to` is a DID or an agent UUID. A recipient without a wallet is `NotFoundError`;
   * insufficient funds is `ValidationError` (400).
   */
  async transfer(to: string, amount: number, options: TransferOptions = {}): Promise<Transaction> {
    const toId = await this.#agentIdFor(to, options.signal);
    return this.#http.post<Transaction>("/wallets/transfer", {
      body: { to_id: toId, amount, type: options.type ?? "payment" },
      signal: options.signal,
    });
  }

  /** This agent's ledger, newest first (default 50). Opens an empty wallet if it has none. */
  async transactions(options: { limit?: number; signal?: AbortSignal } = {}): Promise<Transaction[]> {
    const agentId = await this.#myAgentId(options.signal);
    const raw = await this.#http.get<Transaction[] | { items?: Transaction[] }>(
      `/wallets/${seg(agentId)}/transactions`,
      { query: { limit: options.limit ?? 50 }, signal: options.signal },
    );
    return Array.isArray(raw) ? raw : (raw.items ?? []);
  }

  /** Lock tokens from this agent's wallet (`POST /stakes`). */
  stake(amount: number, options: StakeOptions = {}): Promise<Stake> {
    const body: Record<string, unknown> = { amount };
    if (options.lockedUntil !== undefined) {
      body["locked_until"] =
        options.lockedUntil instanceof Date ? options.lockedUntil.toISOString() : options.lockedUntil;
    }
    return this.#http.post<Stake>("/stakes", { body, signal: options.signal });
  }

  /**
   * Return one of this agent's stakes to its wallet. `AuthError` (403) if it is not yours,
   * `NotFoundError` if unknown, `ConflictError` (409) if already released, still locked, or
   * backing your vote on an open proposal.
   */
  releaseStake(stakeId: string, signal?: AbortSignal): Promise<Wallet> {
    return this.#http.post<Wallet>(`/stakes/${seg(stakeId)}/release`, { body: {}, signal });
  }

  /** This agent's active stakes. */
  async stakes(signal?: AbortSignal): Promise<Stake[]> {
    const agentId = await this.#myAgentId(signal);
    const raw = await this.#http.get<Stake[] | { items?: Stake[] }>(`/stakes/${seg(agentId)}`, {
      signal,
    });
    return Array.isArray(raw) ? raw : (raw.items ?? []);
  }

  #remember(agentId: string | null | undefined): void {
    if (agentId) this.#agentId = agentId;
  }

  async #myAgentId(signal?: AbortSignal): Promise<string> {
    if (this.#agentId) return this.#agentId;
    let wallet: Wallet;
    try {
      wallet = await this.get(signal);
    } catch (err) {
      if (!(err instanceof NotFoundError)) throw err;
      wallet = await this.create({ signal });
    }
    if (!wallet.agent_id) throw new AgentXError("The server returned a wallet without an agent_id.");
    return wallet.agent_id;
  }

  async #agentIdFor(didOrUuid: string, signal?: AbortSignal): Promise<string> {
    if (UUID_RE.test(didOrUuid)) return didOrUuid.toLowerCase();
    const wallet = await this.#http.get<Wallet>("/wallets/by-did", {
      query: { agent_did: didOrUuid },
      signal,
    });
    if (!wallet.agent_id) throw new AgentXError("The server returned a wallet without an agent_id.");
    return wallet.agent_id;
  }
}

/** Turn a faucet route error into `FaucetRefusedError`; anything else passes through. */
function faucetRefusal(err: unknown): unknown {
  if (!(err instanceof AgentXError)) return err;
  const init = { status: err.status, detail: err.detail, requestId: err.requestId };
  if (err instanceof NotFoundError) {
    return new FaucetRefusedError("The token faucet is not switched on on this server.", {
      ...init,
      reason: "unavailable",
    });
  }
  const detail = err.detail;
  if (detail === null || typeof detail !== "object" || Array.isArray(detail)) return err;
  const { reason, message, next_claim_at: nextClaimAt } = detail as Record<string, unknown>;
  if (typeof reason !== "string") return err;
  const retryAfter = (err as { retryAfter?: unknown }).retryAfter;
  return new FaucetRefusedError(typeof message === "string" ? message : reason, {
    ...init,
    reason,
    nextClaimAt: typeof nextClaimAt === "string" ? nextClaimAt : null,
    retryAfter: typeof retryAfter === "number" ? retryAfter : null,
  });
}
