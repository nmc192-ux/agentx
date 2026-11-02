"use client";
/**
 * Phone tab bar (below `md`). Its tabs are the `phone` items of the shell's
 * left menu (lib/nav.ts PHONE_TAB_ITEMS: Home, Explore, Notifications,
 * Messages, Profile), so the two menus always agree; on wider screens the
 * left menu takes over. h-14 for tap targets, and `safe-area-inset-bottom`
 * so it clears the iOS home indicator.
 */
import Link from "next/link";
import { LAYER_FLAGS } from "@/lib/flags";
import { visibleItems } from "@/lib/layers";
import { PHONE_TAB_ITEMS, isMenuItemActive } from "@/lib/nav";
import { UnreadBadge, useShellNav } from "./useShellNav";

const TABS = visibleItems(PHONE_TAB_ITEMS, LAYER_FLAGS);

export function MobileBottomNav() {
  const { pathname, ownProfile, unread } = useShellNav();

  return (
    <nav
      className="md:hidden fixed bottom-0 inset-x-0 z-40 h-14 border-t border-slate-200 dark:border-slate-800 bg-background-light/95 dark:bg-background-dark/95 backdrop-blur-md flex items-stretch"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      aria-label="Primary navigation"
    >
      {TABS.map((item) => {
        const active = isMenuItemActive(pathname, item.href, ownProfile);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-label={item.label}
            aria-current={active ? "page" : undefined}
            className={`relative flex flex-col items-center justify-center gap-0.5 flex-1 h-full transition-colors ${
              active
                ? "text-primary"
                : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100"
            }`}
          >
            <span className="relative">
              <span className="material-symbols-outlined text-[22px]">{item.icon}</span>
              {item.href === "/notifications" && <UnreadBadge count={unread} />}
            </span>
            <span className="text-[10px] font-medium leading-none">{item.phoneLabel ?? item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
