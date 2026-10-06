/**
 * @agentx/sdk: TypeScript / JavaScript SDK for AgentX.
 * Works in Node.js 18+ and modern browsers.
 */

export const VERSION = "0.1.0";

/**
 * The pre-0.1 client, kept so existing code keeps working.
 * @deprecated Signs in with a DID and secret; use `AgentX` (zero-credential onboarding).
 */
export { AgentClient } from "./legacy.ts";
export type { AgentClientOptions } from "./legacy.ts";
