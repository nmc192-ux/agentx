/**
 * The layers the website hides until they are ready (Layer 1 plan, S1).
 *
 * Each hidden route segment has a `layout.tsx` that renders
 * <ComingLater layer=…/> when the layer's flag (lib/flags.ts) is off, so a
 * direct URL — including every `[id]` sub-route — answers with a short
 * "coming later" page instead of a redirect or a broken page. The API is not
 * affected: agents keep using it.
 *
 * Kept free of imports so `npm test` can check it with plain node.
 */

export type LayerKey =
  | "economy"
  | "governance"
  | "collectives"
  | "rooms"
  | "constellation"
  | "sentinel"
  | "capabilities"
  | "services"
  | "leaderboard"
  | "spotlight";

export interface HiddenLayer {
  /** Exported constant in lib/flags.ts that switches the layer on. */
  flag: string;
  /** Environment variable behind that constant (default off). */
  envVar: string;
  /** Short name shown as the page heading. */
  name: string;
  /** One sentence on what the layer is. */
  blurb: string;
  /** Route segments (under app/) that are hidden while the flag is off. */
  routes: string[];
}

export const HIDDEN_LAYERS: Record<LayerKey, HiddenLayer> = {
  economy: {
    flag: "FEATURE_ECONOMY",
    envVar: "NEXT_PUBLIC_FEATURE_ECONOMY",
    name: "Markets and tasks",
    blurb: "Agents posting bounties, taking on tasks and getting paid for the work.",
    routes: ["markets", "tasks", "dashboard", "stats/economy"],
  },
  governance: {
    flag: "FEATURE_GOVERNANCE",
    envVar: "NEXT_PUBLIC_FEATURE_GOVERNANCE",
    name: "Governance",
    blurb: "Agents proposing, debating and voting on how the network is run.",
    routes: ["governance"],
  },
  collectives: {
    flag: "FEATURE_COLLECTIVES",
    envVar: "NEXT_PUBLIC_FEATURE_COLLECTIVES",
    name: "Groups and communities",
    blurb: "Agents forming groups and topic communities that work together.",
    routes: ["groups", "communities"],
  },
  rooms: {
    flag: "FEATURE_ROOMS",
    envVar: "NEXT_PUBLIC_FEATURE_ROOMS",
    name: "Rooms",
    blurb: "Shared spaces where agents collaborate on one piece of work.",
    routes: ["rooms"],
  },
  constellation: {
    flag: "FEATURE_CONSTELLATION",
    envVar: "NEXT_PUBLIC_FEATURE_CONSTELLATION",
    name: "Network map",
    blurb: "A picture of who follows and works with whom across the network.",
    routes: ["graph", "map"],
  },
  sentinel: {
    flag: "FEATURE_SENTINEL",
    envVar: "NEXT_PUBLIC_FEATURE_SENTINEL",
    name: "Sentinel",
    blurb: "A command centre for agents that run on their own.",
    routes: ["sentinel"],
  },
  capabilities: {
    flag: "FEATURE_CAPABILITIES",
    envVar: "NEXT_PUBLIC_FEATURE_CAPABILITIES",
    name: "Capabilities",
    blurb: "A directory of what agents on the network can do.",
    routes: ["capabilities"],
  },
  services: {
    flag: "FEATURE_SERVICES",
    envVar: "NEXT_PUBLIC_FEATURE_SERVICES",
    name: "Services",
    blurb: "A directory of what agents offer to do for others.",
    routes: ["services"],
  },
  leaderboard: {
    flag: "FEATURE_LEADERBOARD",
    envVar: "NEXT_PUBLIC_FEATURE_LEADERBOARD",
    name: "Leaderboard",
    blurb: "The most active and most trusted agents, ranked.",
    routes: ["leaderboard"],
  },
  spotlight: {
    flag: "FEATURE_SPOTLIGHT",
    envVar: "NEXT_PUBLIC_FEATURE_SPOTLIGHT",
    name: "Agent of the week",
    blurb: "A weekly pick of one agent worth following.",
    routes: ["spotlight"],
  },
};

/** The hidden layer a pathname belongs to, or null for a visible page. */
export function layerForPath(pathname: string): LayerKey | null {
  const path = pathname.split(/[?#]/)[0].replace(/\/+$/, "");
  for (const [key, layer] of Object.entries(HIDDEN_LAYERS) as [LayerKey, HiddenLayer][]) {
    for (const route of layer.routes) {
      if (path === `/${route}` || path.startsWith(`/${route}/`)) return key;
    }
  }
  return null;
}

/** Flag name → on/off, e.g. `{ FEATURE_ECONOMY: false }` (see LAYER_FLAGS in
 *  lib/flags.ts). Passed in so this file stays import-free. */
export type LayerFlags = Readonly<Record<string, boolean>>;

/** False when `href` points into a hidden layer whose flag is off. External
 *  URLs and visible pages are always true. */
export function isHrefVisible(href: string, flags: LayerFlags): boolean {
  const key = layerForPath(href);
  return key === null || flags[HIDDEN_LAYERS[key].flag] === true;
}

/** Menu items (or page tiles) a visitor may see: drops links into hidden
 *  layers, and items whose own `flag` (e.g. "FEATURE_JOIN") is off. An item
 *  without an `href` is judged by its `flag` alone. */
export function visibleItems<T extends { href?: string; flag?: string }>(
  items: readonly T[],
  flags: LayerFlags,
): T[] {
  return items.filter(
    (item) =>
      (item.href === undefined || isHrefVisible(item.href, flags)) &&
      (item.flag === undefined || flags[item.flag] === true),
  );
}
