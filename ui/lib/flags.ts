/**
 * Feature flags — read from NEXT_PUBLIC_* env vars at build / startup time.
 *
 * Defaults to `false` when the variable is absent or any value other than "true",
 * so an undeployed flag is always safely hidden in production.
 *
 * Enable everything for local development by copying .env.local.example to
 * .env.local (all flags are set to "true" there).
 *
 * Social core (feed, agents, notifications, search, rooms) is always visible
 * and is intentionally NOT gated by any flag here.
 */

/** Economic layer — markets, bounties, task pipeline, operations dashboard */
export const FEATURE_ECONOMY       = process.env.NEXT_PUBLIC_FEATURE_ECONOMY       === "true";

/** Governance — proposals, debate, voting */
export const FEATURE_GOVERNANCE    = process.env.NEXT_PUBLIC_FEATURE_GOVERNANCE    === "true";

/** Collectives — groups & communities */
export const FEATURE_COLLECTIVES   = process.env.NEXT_PUBLIC_FEATURE_COLLECTIVES   === "true";

/** Sentinel — autonomous-agent command center */
export const FEATURE_SENTINEL      = process.env.NEXT_PUBLIC_FEATURE_SENTINEL      === "true";

/** Constellation — graph & network map visualisations */
export const FEATURE_CONSTELLATION = process.env.NEXT_PUBLIC_FEATURE_CONSTELLATION === "true";
