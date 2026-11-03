// A URL path whose percent escapes do not decode (`/agents/%E0%A4%A`, `/tag/abc%ZZ`)
// made Next answer 500 before any page ran. `proxy.ts` sends such a path to the
// normal 404 page instead. Kept here, free of Next imports, so `npm test` covers it.

/** Where a malformed path is rewritten to: no route matches it, so Next serves not-found. */
export const NOT_FOUND_PATH = "/_agentx_not_found";

/** True when every `%` escape in `pathname` decodes (as UTF-8) per segment. */
export function pathDecodes(pathname: string): boolean {
  if (!pathname.includes("%")) return true;
  try {
    for (const part of pathname.split("/")) decodeURIComponent(part);
    return true;
  } catch {
    return false;
  }
}
