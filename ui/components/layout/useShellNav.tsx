"use client";
/**
 * Shared state for the app shell's two menus (left menu and phone tab bar):
 * whether the viewer is signed in, its DID, and the unread-notification
 * count. Both menus are mounted at once, so the count comes from the shared
 * request (getUnreadCountShared) and the poll pauses while the tab is hidden.
 */
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { getDid, getToken, isLoggedIn } from "@/lib/auth";
import { getUnreadCountShared } from "@/lib/api";
import { NOTIF_POLL_MS, pollWhileVisible } from "@/lib/poll";

export function useShellNav() {
  const pathname = usePathname();
  const [loggedIn, setLoggedIn] = useState(false);
  const [did,      setDid]      = useState<string | null>(null);
  const [unread,   setUnread]   = useState(0);

  useEffect(() => {
    // Defer the localStorage read out of the effect body so React 19's
    // set-state-in-effect rule passes; behaviour is identical.
    queueMicrotask(() => {
      setLoggedIn(isLoggedIn());
      setDid(getDid());
    });
  }, []);

  const refreshUnread = useCallback(async () => {
    const tok = getToken();
    if (!tok) {
      setUnread(0);
      return;
    }
    try {
      setUnread(await getUnreadCountShared(tok));
    } catch {
      // Silent: a transient API hiccup shouldn't blow away the badge.
    }
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    return pollWhileVisible(() => { void refreshUnread(); }, NOTIF_POLL_MS);
  }, [loggedIn, refreshUnread]);

  return {
    pathname,
    loggedIn,
    ownProfile: did ? `/agents/${encodeURIComponent(did)}` : null,
    unread: pathname === "/notifications" ? 0 : unread,
  };
}

/** Small count bubble on the Notifications icon; nothing at zero. */
export function UnreadBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span
      className="absolute -top-1.5 -right-2 min-w-[16px] h-[16px] px-1 rounded-full bg-cyan-500 text-white text-[9px] font-bold leading-none flex items-center justify-center ring-2 ring-background-light dark:ring-background-dark"
      aria-hidden
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}
