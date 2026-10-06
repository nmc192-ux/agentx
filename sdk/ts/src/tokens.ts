/**
 * Holds an agent's access / refresh token pair and keeps it fresh.
 *
 * AgentX has no password login: an agent gets its first pair from `POST /onboard` and
 * renews it with `POST /auth/token` (`grant_type=refresh_token`, form fields). The
 * access token is refreshed 60 s before its `exp`, one refresh at a time however many
 * calls are waiting. Tokens live in private fields so `console.log(tokens)` and
 * `JSON.stringify` never print them.
 */

import { AuthError } from "./errors.ts";

/** Refresh this many milliseconds before the access token expires. */
export const REFRESH_MARGIN_MS = 60_000;

/** Used when neither `expires_in` nor the token's `exp` claim says otherwise. */
export const DEFAULT_ACCESS_TOKEN_TTL_MS = 3_600_000;

/** A token pair as the SDK stores it. `expiresAt` is epoch milliseconds. */
export interface TokenPair {
  accessToken: string;
  refreshToken?: string | undefined;
  expiresAt?: number | undefined;
}

/** The body of `POST /onboard` and `POST /auth/token` responses (fields the SDK reads). */
export interface TokenResponse {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  [key: string]: unknown;
}

/** Exchanges a refresh token for a new pair. Supplied by the HTTP client. */
export type RefreshFn = (refreshToken: string) => Promise<TokenResponse>;

/** Called after every successful refresh, e.g. to save the identity file. */
export type OnRefresh = (pair: TokenPair) => void | Promise<void>;

function base64UrlDecode(part: string): string {
  const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

/**
 * The `exp` claim of a JWT in epoch milliseconds, read without verifying the signature.
 * Only used to schedule a refresh; the server still verifies every token. `undefined`
 * when the string is not a JWT or has no numeric `exp`.
 */
export function jwtExpiry(token: string): number | undefined {
  try {
    const payload = token.split(".")[1];
    if (!payload) return undefined;
    const claims: unknown = JSON.parse(base64UrlDecode(payload));
    const exp = (claims as { exp?: unknown } | null)?.exp;
    return typeof exp === "number" && Number.isFinite(exp) ? exp * 1000 : undefined;
  } catch {
    return undefined;
  }
}

function expiryOf(accessToken: string, expiresIn: number | undefined, now: number): number {
  if (typeof expiresIn === "number" && Number.isFinite(expiresIn)) {
    return now + expiresIn * 1000;
  }
  return jwtExpiry(accessToken) ?? now + DEFAULT_ACCESS_TOKEN_TTL_MS;
}

export class TokenManager {
  #accessToken: string;
  #refreshToken: string | undefined;
  #expiresAt: number;
  #inflight: Promise<string> | undefined;
  #refreshFn: RefreshFn | undefined;
  #onRefresh: OnRefresh | undefined;
  readonly #now: () => number;

  constructor(
    pair: TokenPair,
    options: { refresh?: RefreshFn; onRefresh?: OnRefresh; now?: () => number } = {},
  ) {
    if (!pair.accessToken) throw new AuthError("An access token is required.");
    this.#now = options.now ?? Date.now;
    this.#accessToken = pair.accessToken;
    this.#refreshToken = pair.refreshToken || undefined;
    this.#expiresAt = pair.expiresAt ?? expiryOf(pair.accessToken, undefined, this.#now());
    this.#refreshFn = options.refresh;
    this.#onRefresh = options.onRefresh;
  }

  /** @internal The HTTP client wires itself in here. */
  setRefreshFn(fn: RefreshFn): void {
    this.#refreshFn = fn;
  }

  /** Register a callback run after each successful refresh (replaces any earlier one). */
  setOnRefresh(fn: OnRefresh | undefined): void {
    this.#onRefresh = fn;
  }

  /** A copy of the current pair, e.g. for saving to disk. Treat it as a secret. */
  snapshot(): TokenPair {
    return {
      accessToken: this.#accessToken,
      refreshToken: this.#refreshToken,
      expiresAt: this.#expiresAt,
    };
  }

  get expiresAt(): number {
    return this.#expiresAt;
  }

  get canRefresh(): boolean {
    return this.#refreshToken !== undefined && this.#refreshFn !== undefined;
  }

  /** True when the access token is within the refresh margin of expiry. */
  needsRefresh(): boolean {
    return this.#now() >= this.#expiresAt - REFRESH_MARGIN_MS;
  }

  /**
   * The access token to send now. Refreshes first when it is about to expire and a
   * refresh token is held; otherwise returns the current one and lets the server decide.
   */
  async accessToken(): Promise<string> {
    if (this.#inflight) return this.#inflight;
    if (this.needsRefresh() && this.canRefresh) return this.refresh();
    return this.#accessToken;
  }

  /**
   * Called after a 401. Refreshes unless another call already replaced `rejected`, in
   * which case the newer token is returned without a second refresh.
   */
  async refreshAfterReject(rejected: string): Promise<string> {
    if (this.#inflight) return this.#inflight;
    if (this.#accessToken !== rejected) return this.#accessToken;
    return this.refresh();
  }

  /** Exchange the refresh token for a new pair. Concurrent callers share one request. */
  refresh(): Promise<string> {
    if (this.#inflight) return this.#inflight;
    const run = this.#doRefresh();
    this.#inflight = run;
    // Clear on settle so a failed refresh can be tried again by a later call.
    const clear = (): void => {
      if (this.#inflight === run) this.#inflight = undefined;
    };
    run.then(clear, clear);
    return run;
  }

  async #doRefresh(): Promise<string> {
    const refreshToken = this.#refreshToken;
    const refreshFn = this.#refreshFn;
    if (!refreshToken || !refreshFn) {
      throw new AuthError(
        "The access token has expired or was refused and no refresh token is held. " +
          "Onboard again with AgentX.onboard(...) or load a saved identity.",
      );
    }
    let data: TokenResponse;
    try {
      data = await refreshFn(refreshToken);
    } catch (err) {
      if (err instanceof AuthError) {
        throw new AuthError(
          "Token refresh was refused: the refresh token is invalid or expired, or the " +
            "agent is not active. Onboard again or load a fresh identity.",
          { status: err.status, detail: err.detail, requestId: err.requestId },
        );
      }
      throw err;
    }
    const access = data.access_token;
    if (typeof access !== "string" || access === "") {
      throw new AuthError("Token refresh response carried no access token.");
    }
    this.#accessToken = access;
    if (typeof data.refresh_token === "string" && data.refresh_token !== "") {
      this.#refreshToken = data.refresh_token;
    }
    this.#expiresAt = expiryOf(access, data.expires_in, this.#now());
    if (this.#onRefresh) await this.#onRefresh(this.snapshot());
    return access;
  }

  /** Never reveal tokens when logged or serialised. */
  toJSON(): Record<string, unknown> {
    return { expiresAt: this.#expiresAt, hasRefreshToken: this.#refreshToken !== undefined };
  }
}
