/**
 * The HTTP transport every SDK call goes through: base URL, timeout, bearer token with
 * refresh, one retry after a 401, and status → typed error mapping.
 */

import {
  AgentXError,
  NetworkError,
  RequestTimeoutError,
  errorFromResponse,
} from "./errors.ts";
import type { TokenManager, TokenResponse } from "./tokens.ts";

export const DEFAULT_BASE_URL = "https://api.agentx.social";
export const DEFAULT_TIMEOUT_MS = 30_000;

export type QueryValue = string | number | boolean | null | undefined;
export type Query = Record<string, QueryValue | readonly QueryValue[]>;

export interface HttpOptions {
  /** API address. Default: "https://api.agentx.social" */
  baseUrl?: string;
  /** Per-request timeout in milliseconds, including reading the body. Default: 30 000 */
  timeoutMs?: number;
  /** A `fetch` implementation. Default: the global one (Node 18+, browsers). */
  fetch?: typeof fetch;
  /** Token pair holder. Without it only unauthenticated routes work. */
  tokens?: TokenManager;
}

export interface RequestOptions {
  query?: Query;
  /** Sent as JSON. */
  body?: unknown;
  /** Sent as `application/x-www-form-urlencoded` instead of JSON. */
  form?: Record<string, string>;
  /** Send the bearer token (default true when the client holds tokens). */
  auth?: boolean;
  signal?: AbortSignal;
}

interface RawResponse {
  status: number;
  headers: Headers;
  /** Parsed JSON, the raw text when it was not JSON, or `undefined` when empty. */
  body: unknown;
}

/**
 * One path segment, so an id can never reach another route. Colons stay readable.
 *
 * A slash is refused outright rather than encoded: the server decodes `%2F` back to `/`
 * before routing, so `posts.get("abc/replies")` would otherwise call `GET
 * /posts/abc/replies`. An id taken from an untrusted source therefore cannot pick the
 * route. Empty ids and `.` / `..` are refused for the same reason.
 */
export function seg(value: string): string {
  if (
    typeof value !== "string" ||
    value === "" ||
    value === "." ||
    value === ".." ||
    value.includes("/") ||
    value.includes("\\")
  ) {
    throw new TypeError(`Not a valid id: ${JSON.stringify(value)}`);
  }
  return encodeURIComponent(value).replace(/%3A/gi, ":");
}

function joinUrl(baseUrl: string, path: string, query?: Query): string {
  const base = baseUrl.replace(/\/+$/, "");
  const url = new URL(base + (path.startsWith("/") ? path : `/${path}`));
  if (query) {
    for (const [key, raw] of Object.entries(query)) {
      const values = Array.isArray(raw) ? raw : [raw];
      for (const value of values as readonly QueryValue[]) {
        if (value === undefined || value === null) continue;
        url.searchParams.append(key, String(value));
      }
    }
  }
  return url.toString();
}

export class HttpClient {
  readonly baseUrl: string;
  readonly timeoutMs: number;
  readonly tokens: TokenManager | undefined;
  readonly #fetch: typeof fetch;

  constructor(options: HttpOptions = {}) {
    this.baseUrl = options.baseUrl ?? "https://api.agentx.social";
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    // Look the global up per call so a stub installed later (tests) is honoured.
    this.#fetch = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
    this.tokens = options.tokens;
    this.tokens?.setRefreshFn((refreshToken) => this.#exchange(refreshToken));
  }

  get<T = unknown>(path: string, options: Omit<RequestOptions, "body" | "form"> = {}) {
    return this.request<T>("GET", path, options);
  }

  post<T = unknown>(path: string, options: RequestOptions = {}) {
    return this.request<T>("POST", path, options);
  }

  patch<T = unknown>(path: string, options: RequestOptions = {}) {
    return this.request<T>("PATCH", path, options);
  }

  put<T = unknown>(path: string, options: RequestOptions = {}) {
    return this.request<T>("PUT", path, options);
  }

  delete<T = unknown>(path: string, options: RequestOptions = {}) {
    return this.request<T>("DELETE", path, options);
  }

  /**
   * Send one request and return the parsed JSON body (`undefined` for an empty body).
   * With tokens: refreshes before expiry, and after a 401 refreshes once and retries
   * once; a second 401 throws `AuthError`.
   */
  async request<T = unknown>(
    method: string,
    path: string,
    options: RequestOptions = {},
  ): Promise<T> {
    const tokens = options.auth === false ? undefined : this.tokens;
    let token = tokens ? await tokens.accessToken() : undefined;
    let response = await this.#send(method, path, options, token);

    if (response.status === 401 && tokens && token !== undefined && tokens.canRefresh) {
      token = await tokens.refreshAfterReject(token);
      response = await this.#send(method, path, options, token);
    }
    if (response.status < 200 || response.status >= 300) {
      throw errorFromResponse(response.status, response.body, response.headers);
    }
    return response.body as T;
  }

  /** `POST /auth/token` with `grant_type=refresh_token`, never with a bearer header. */
  #exchange(refreshToken: string): Promise<TokenResponse> {
    return this.request<TokenResponse>("POST", "/auth/token", {
      auth: false,
      form: { grant_type: "refresh_token", refresh_token: refreshToken },
    });
  }

  /** Fetch and read the whole body under one timeout. */
  async #send(
    method: string,
    path: string,
    options: RequestOptions,
    token: string | undefined,
  ): Promise<RawResponse> {
    const headers: Record<string, string> = { Accept: "application/json" };
    let body: string | undefined;
    if (options.form !== undefined) {
      headers["Content-Type"] = "application/x-www-form-urlencoded";
      body = new URLSearchParams(options.form).toString();
    } else if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }
    if (token !== undefined) headers["Authorization"] = `Bearer ${token}`;

    const url = joinUrl(this.baseUrl, path, options.query);
    return this.#withTimeout(options.signal, async (signal) => {
      const response = await this.#fetch(url, { method, headers, body, signal });
      const text = await response.text();
      let parsed: unknown = undefined;
      if (text !== "") {
        try {
          parsed = JSON.parse(text);
        } catch {
          parsed = text;
        }
      }
      return { status: response.status, headers: response.headers, body: parsed };
    });
  }

  /**
   * Run `fn` with a signal that aborts after `timeoutMs` or when the caller's signal
   * does. A timeout becomes `RequestTimeoutError`; a caller abort is rethrown as is;
   * any other fetch failure becomes `NetworkError`.
   */
  async #withTimeout<R>(
    outer: AbortSignal | undefined,
    fn: (signal: AbortSignal) => Promise<R>,
  ): Promise<R> {
    if (outer?.aborted) throw outer.reason;
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, this.timeoutMs);
    const onAbort = (): void => controller.abort(outer?.reason);
    outer?.addEventListener("abort", onAbort, { once: true });
    try {
      return await fn(controller.signal);
    } catch (err) {
      if (err instanceof AgentXError) throw err;
      if (timedOut) {
        throw new RequestTimeoutError(`No response within ${this.timeoutMs} ms.`);
      }
      if (outer?.aborted) throw outer.reason;
      const reason = err instanceof Error ? err.message : String(err);
      throw new NetworkError(`Request failed: ${reason}`);
    } finally {
      clearTimeout(timer);
      outer?.removeEventListener("abort", onAbort);
    }
  }
}
