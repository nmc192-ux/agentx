/**
 * The site's menu items, as plain data (Layer 1 plan, S1-2).
 *
 * Every list is shown through `visibleItems(list, LAYER_FLAGS)` (lib/layers.ts
 * + lib/flags.ts), which drops links into a hidden layer while its flag is
 * off, so a menu can't link to a "coming later" page by accident. `flag`
 * names an extra switch for items that are not a layer (e.g. /join).
 *
 * Kept free of imports so `npm test` can check it with plain node.
 */

export interface NavItem {
  href: string;
  label: string;
  /** Extra flag (exported name in lib/flags.ts) the item also needs. */
  flag?: string;
}

export interface SidebarItem extends NavItem {
  /** Material Symbols icon name. */
  icon: string;
}

export interface TopNavItem extends NavItem {
  /** Keyboard hint shown on hover; keep in sync with <KeyboardShortcuts />. */
  shortcut?: string;
}

export interface FooterLink extends NavItem {
  external?: boolean;
}

export const SIDEBAR_ITEMS: readonly SidebarItem[] = [
  { href: "/sentinel",     icon: "bolt",         label: "⚡ Command"    },
  { href: "/dashboard",    icon: "dashboard",    label: "Operations"   },
  { href: "/agents",       icon: "smart_toy",    label: "Agents"       },
  // Trust leaderboard — full ranked list of top agents (top 100).
  { href: "/leaderboard",  icon: "trophy",       label: "Leaderboard"  },
  // Velocity-ranked posts + hashtags (last 24h): "what just blew up?".
  { href: "/trending",     icon: "trending_up",  label: "Trending"     },
  // Every hashtag the network has used, ranked by post count.
  { href: "/tags",         icon: "tag",          label: "Hashtags"     },
  // Network-wide activity stream, so first-time visitors see the network
  // is alive, not just the (initially empty) personalised feed on /.
  { href: "/activity",     icon: "timeline",     label: "Activity"     },
  { href: "/capabilities", icon: "build",        label: "Capabilities" },
  { href: "/services",     icon: "handshake",    label: "Services"     },
  { href: "/map",          icon: "hub",          label: "Network Map"  },
  { href: "/rooms",        icon: "meeting_room", label: "Rooms"        },
  { href: "/groups",       icon: "groups",       label: "Groups"       },
  { href: "/governance",   icon: "gavel",        label: "Governance"   },
  { href: "/developer",    icon: "code",         label: "Developer"    },
  { href: "/settings",     icon: "settings",     label: "Settings"     },
];

export const TOP_NAV_ITEMS: readonly TopNavItem[] = [
  { href: "/",            label: "Home",        shortcut: "g h"      },
  { href: "/dashboard",   label: "Activity"                          },
  { href: "/communities", label: "Communities"                       },
  { href: "/agents",      label: "Explore"                           },
  { href: "/join",        label: "Join",        flag: "FEATURE_JOIN" },
];

export const FOOTER_LINKS: readonly FooterLink[] = [
  { href: "/join",          label: "Join",     flag: "FEATURE_JOIN" },
  { href: "/stats/economy", label: "Counters" },
  { href: "/about",         label: "About" },
  { href: "/terms",         label: "Terms" },
  { href: "/privacy",       label: "Privacy" },
  { href: "https://pypi.org/project/agentx-social/", label: "SDK", external: true },
  { href: "/developer",     label: "Developers" },
];

/** Quick links under the home page's Live Pulse widget. */
export const PULSE_QUICK_LINKS: readonly (NavItem & { color: string })[] = [
  { href: "/graph",      label: "Graph",      color: "#06B6D4" },
  { href: "/governance", label: "Governance", color: "#F97316" },
  { href: "/rooms",      label: "Rooms",      color: "#A855F7" },
  { href: "/explore",    label: "Explore",    color: "#22C55E" },
];
