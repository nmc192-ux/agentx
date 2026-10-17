/**
 * Polling cadence for the website (EG-6, Neon egress).
 *
 * Every poll is a database read on the free plan's transfer budget, so the
 * intervals below are the slowest that still feel live, and every poller
 * skips its tick while the tab is hidden. Anonymous public reads are served
 * from the API's 30–60 s response cache, so polling them faster than that
 * only re-downloads the same answer.
 */

/** Unread-notification badge (bell + mobile nav share one request). */
export const NOTIF_POLL_MS = 60_000;
/** Pulse vitals, ops dashboard lists and the developer page event log. */
export const LIVE_POLL_MS = 60_000;
/** Ops activity feed: the one view meant to be watched as it happens. */
export const FEED_POLL_MS = 30_000;
/** API health dot. */
export const HEALTH_POLL_MS = 60_000;

/**
 * Run `fn` now and then every `ms`, skipping ticks while the tab is hidden
 * and catching up once when it becomes visible again. Returns the cleanup.
 */
export function pollWhileVisible(fn: () => void, ms: number): () => void {
  const hidden = () => typeof document !== "undefined" && document.hidden;
  const tick = () => { if (!hidden()) fn(); };
  fn();
  const id = setInterval(tick, ms);
  const onVisibility = () => { if (!hidden()) fn(); };
  document.addEventListener("visibilitychange", onVisibility);
  return () => {
    clearInterval(id);
    document.removeEventListener("visibilitychange", onVisibility);
  };
}
