/**
 * Typed errors. Every failed call throws an `AgentXError` subclass picked from the HTTP
 * status, so callers can `catch (e) { if (e instanceof RateLimitError) ... }`.
 *
 * Messages carry the server's `detail` text only, never a token or a request header.
 */

/** Root of every error this SDK throws. */
export class AgentXError extends Error {
  /** HTTP status, when the error came from a response. */
  readonly status: number | undefined;
  /** The server's `detail` field as sent (string or validation list), if any. */
  readonly detail: unknown;
  /** The server's `request_id`, useful when reporting a problem. */
  readonly requestId: string | undefined;

  constructor(
    message: string,
    init: { status?: number; detail?: unknown; requestId?: string } = {},
  ) {
    super(message);
    this.name = new.target.name;
    this.status = init.status;
    this.detail = init.detail;
    this.requestId = init.requestId;
  }
}

/** 401 / 403: the token is missing, expired, refused, or not allowed to do this. */
export class AuthError extends AgentXError {}

/** 404: the thing does not exist (or the route is switched off on this server). */
export class NotFoundError extends AgentXError {}

/** 409: the request clashes with current state (already done, wrong status, taken). */
export class ConflictError extends AgentXError {}

/** 400 / 422: the request body or query failed validation. */
export class ValidationError extends AgentXError {}

/** 429: too many requests. Wait `retryAfter` seconds before trying again. */
export class RateLimitError extends AgentXError {
  readonly retryAfter: number;

  constructor(
    message: string,
    init: { status?: number; detail?: unknown; requestId?: string; retryAfter?: number } = {},
  ) {
    super(message, init);
    this.retryAfter = init.retryAfter ?? 1;
  }
}

/** 5xx: the platform failed. Usually safe to retry later. */
export class ServerError extends AgentXError {}

/** The request never got a response (DNS, refused connection, reset). */
export class NetworkError extends AgentXError {}

/** No response within the client's timeout. */
export class RequestTimeoutError extends NetworkError {}

/** Seconds from a `Retry-After` header (delta-seconds or HTTP date); 1 when absent or bad. */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number {
  if (value === null || value.trim() === "") return 1;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return Number(trimmed);
  const when = Date.parse(trimmed);
  if (Number.isNaN(when)) return 1;
  return Math.max(0, Math.ceil((when - now) / 1000));
}

function describe(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc: [...], msg: "..."}, ...]
    const parts = detail.map((item) => {
      if (item && typeof item === "object" && "msg" in item) {
        const loc = Array.isArray((item as { loc?: unknown }).loc)
          ? ((item as { loc: unknown[] }).loc).join(".")
          : "";
        const msg = String((item as { msg: unknown }).msg);
        return loc ? `${loc}: ${msg}` : msg;
      }
      return JSON.stringify(item);
    });
    return parts.join("; ");
  }
  if (detail !== undefined && detail !== null) return JSON.stringify(detail);
  return undefined;
}

/**
 * Build the typed error for a non-2xx response. `body` is the parsed JSON body (or the
 * raw text when it was not JSON).
 */
export function errorFromResponse(
  status: number,
  body: unknown,
  headers: Headers,
): AgentXError {
  let detail: unknown;
  let requestId: string | undefined;
  if (body && typeof body === "object" && !Array.isArray(body)) {
    detail = (body as { detail?: unknown }).detail;
    const rid = (body as { request_id?: unknown }).request_id;
    if (typeof rid === "string") requestId = rid;
  } else if (typeof body === "string" && body !== "") {
    detail = body;
  }
  const message = `HTTP ${status}: ${describe(detail) ?? "no detail"}`;
  const init = { status, detail, requestId };

  if (status === 401 || status === 403) return new AuthError(message, init);
  if (status === 404) return new NotFoundError(message, init);
  if (status === 409) return new ConflictError(message, init);
  if (status === 400 || status === 422) return new ValidationError(message, init);
  if (status === 429) {
    return new RateLimitError(message, {
      ...init,
      retryAfter: parseRetryAfter(headers.get("Retry-After")),
    });
  }
  if (status >= 500) return new ServerError(message, init);
  return new AgentXError(message, init);
}
