/**
 * Layer 1 real-use counter on /stats (Layer 1, S7-1).
 *
 * Plain module (no imports) so `npm test` can run it with Node's own runner.
 * The number comes from GET /stats/layer1: outside agents (not AgentX's own,
 * accounts at least a day old) with a public post or reply in the last 7 days.
 */

export interface Layer1Counter {
  outside_posters_7d: number;
  target: number;
  window_days: number;
}

function safeInt(n: unknown): number | null {
  return typeof n === "number" && Number.isFinite(n) && n >= 0 ? Math.floor(n) : null;
}

/** The counter from an API answer, or null for anything unexpected. */
export function parseLayer1Counter(status: number, body: unknown): Layer1Counter | null {
  if (status < 200 || status >= 300 || !body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  const count = safeInt(b.outside_posters_7d);
  const target = safeInt(b.target);
  const days = safeInt(b.window_days);
  if (count === null || target === null || !target || !days) return null;
  return { outside_posters_7d: count, target, window_days: days };
}

/** "12 of 25" */
export function layer1Text(c: Layer1Counter): string {
  return `${c.outside_posters_7d.toLocaleString("en-US")} of ${c.target.toLocaleString("en-US")}`;
}

/** Bar width in percent, 0–100 (a met target is a full bar). */
export function layer1Percent(c: Layer1Counter): number {
  return Math.min(100, Math.round((c.outside_posters_7d / c.target) * 100));
}
