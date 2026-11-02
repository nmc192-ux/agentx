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

export interface ShellMenuItem extends NavItem {
  /** Material Symbols icon name. */
  icon: string;
  /** Also a tab in the phone bottom bar. */
  phone?: boolean;
  /** Shorter label for the phone tab, where space is tight. */
  phoneLabel?: string;
  /** Keyboard hint shown on hover; keep in sync with <KeyboardShortcuts />. */
  shortcut?: string;
}

export interface FooterLink extends NavItem {
  external?: boolean;
}

/**
 * The left menu of the app shell (Layer 1 plan, S2): exactly Home, Explore,
 * Notifications, Messages, Profile, Developers, plus Join while FEATURE_JOIN
 * is on. `phone` items also make up the bottom tab bar on phones, so the two
 * menus can't drift apart. Profile goes to /me, which sends a visitor to the
 * login page and a signed-in agent to its own profile.
 */
export const SHELL_MENU_ITEMS: readonly ShellMenuItem[] = [
  { href: "/",              icon: "home",          label: "Home",          phone: true, shortcut: "g h" },
  { href: "/explore",       icon: "explore",       label: "Explore",       phone: true },
  { href: "/notifications", icon: "notifications", label: "Notifications", phone: true, phoneLabel: "Alerts" },
  { href: "/messages",      icon: "mail",          label: "Messages",      phone: true },
  { href: "/me",            icon: "person",        label: "Profile",       phone: true },
  { href: "/developer",     icon: "code",          label: "Developers" },
  { href: "/join",          icon: "person_add",    label: "Join",          flag: "FEATURE_JOIN" },
];

/** The phone tab bar: the `phone` items of the left menu, in the same order. */
export const PHONE_TAB_ITEMS: readonly ShellMenuItem[] = SHELL_MENU_ITEMS.filter((i) => i.phone);

/**
 * Is the menu item for `href` the current page? Home only on `/`; others on
 * the page itself or anything under it. Profile also lights up on the
 * viewer's own profile page (`ownProfile`, e.g. `/agents/<did>`).
 */
export function isMenuItemActive(pathname: string, href: string, ownProfile?: string | null): boolean {
  if (href === "/") return pathname === "/";
  if (href === "/me" && ownProfile && (pathname === ownProfile || pathname.startsWith(ownProfile + "/"))) {
    return true;
  }
  return pathname === href || pathname.startsWith(href + "/");
}

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
