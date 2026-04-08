/**
 * AgentX — Auth helpers
 * Manages observer token storage and retrieval from localStorage.
 */

const TOKEN_KEY = "agentx_token";
const DID_KEY   = "agentx_did";

/** Read the stored JWT access token, or null if not present. */
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

/** Read the stored agent DID, or null if not present. */
export function getDid(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(DID_KEY);
}

/** Persist the JWT and DID to localStorage. */
export function setToken(token: string, did: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(DID_KEY, did);
}

/** Remove both auth keys from localStorage. */
export function clearToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(DID_KEY);
}

/** Returns true when a token is present in localStorage. */
export function isLoggedIn(): boolean {
  return getToken() !== null;
}
