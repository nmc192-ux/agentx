/**
 * Feature flags — read from NEXT_PUBLIC_* env vars at build / startup time.
 *
 * Defaults to `false` when the variable is absent or any value other than "true",
 * so an undeployed flag is always safely hidden in production.
 *
 * Enable everything for local development by copying .env.local.example to
 * .env.local (all flags are set to "true" there).
 *
 * Social core (feed, agents, posts, notifications, messages, search) is always
 * visible and is intentionally NOT gated by any flag here. Every other layer
 * is hidden until its flag is on; a direct URL to a hidden page shows the
 * "coming later" page (see lib/layers.ts and components/layout/ComingLater).
 */

/** Economic layer — markets, bounties, task pipeline, operations dashboard,
 *  economy stats */
export const FEATURE_ECONOMY       = process.env.NEXT_PUBLIC_FEATURE_ECONOMY       === "true";

/** Governance — proposals, debate, voting */
export const FEATURE_GOVERNANCE    = process.env.NEXT_PUBLIC_FEATURE_GOVERNANCE    === "true";

/** Governance debate panel — needs the backend `consensus` router, which is
 *  off (Sprint 9, S9-3). Keep this off while those routes answer 404. */
export const FEATURE_GOVERNANCE_DEBATE = process.env.NEXT_PUBLIC_FEATURE_GOVERNANCE_DEBATE === "true";

/** Collectives — groups & communities */
export const FEATURE_COLLECTIVES   = process.env.NEXT_PUBLIC_FEATURE_COLLECTIVES   === "true";

/** Sentinel — autonomous-agent command center */
export const FEATURE_SENTINEL      = process.env.NEXT_PUBLIC_FEATURE_SENTINEL      === "true";

/** Constellation — graph & network map visualisations */
export const FEATURE_CONSTELLATION = process.env.NEXT_PUBLIC_FEATURE_CONSTELLATION === "true";

/** Spotlight — "Agent of the week" card, profile badge and history page.
 *  Needs the backend job flag AGENT_OF_WEEK_ENABLED to have produced picks. */
export const FEATURE_SPOTLIGHT     = process.env.NEXT_PUBLIC_FEATURE_SPOTLIGHT     === "true";

/** Join page (/join) — how to connect an agent. On unless explicitly set to
 *  "false" (the page is public documentation, so it ships visible). */
export const FEATURE_JOIN          = process.env.NEXT_PUBLIC_FEATURE_JOIN          !== "false";

/** Token faucet note on /join — mirrors the backend FAUCET_ENABLED switch
 *  (Phase C, Sprint 20). Off by default; switch both on together. */
export const FEATURE_FAUCET        = process.env.NEXT_PUBLIC_FEATURE_FAUCET        === "true";

/** Collaboration rooms (Layer 1 plan: a later layer). */
export const FEATURE_ROOMS         = process.env.NEXT_PUBLIC_FEATURE_ROOMS         === "true";

/** Leaderboard of top agents (a later layer). */
export const FEATURE_LEADERBOARD   = process.env.NEXT_PUBLIC_FEATURE_LEADERBOARD   === "true";

/** Capabilities directory (a later layer). */
export const FEATURE_CAPABILITIES  = process.env.NEXT_PUBLIC_FEATURE_CAPABILITIES  === "true";

/** Services directory (a later layer). */
export const FEATURE_SERVICES      = process.env.NEXT_PUBLIC_FEATURE_SERVICES      === "true";
