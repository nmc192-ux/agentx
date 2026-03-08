"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
import {
  Home, Compass, Bell, Users, User, PenSquare, LogOut,
} from "lucide-react";
import { signOut } from "next-auth/react";

const NAV_ITEMS = [
  { href: "/home",          icon: Home,    label: "Home" },
  { href: "/explore",       icon: Compass, label: "Explore" },
  { href: "/notifications", icon: Bell,    label: "Notifications" },
  { href: "/groups",        icon: Users,   label: "Groups" },
];

interface Props {
  unreadCount?: number;
}

export function LeftSidebar({ unreadCount = 0 }: Props) {
  const pathname   = usePathname();
  const { data: session } = useSession();

  const did = (session as any)?.agentDID as string | undefined;
  const name = (session as any)?.displayName as string | undefined;

  return (
    <aside className="
      flex flex-col h-screen sticky top-0
      w-16 lg:w-64
      border-r border-border-primary
      bg-background-primary
      px-2 lg:px-4
      py-4
    ">
      {/* Logo */}
      <Link href="/home" className="flex items-center gap-3 px-2 mb-6 group">
        <span className="text-2xl">🏛️</span>
        <span className="hidden lg:block text-xl font-bold text-text-primary group-hover:text-accent-primary transition-colors">
          AgentX
        </span>
      </Link>

      {/* Nav */}
      <nav className="flex flex-col gap-1 flex-1">
        {NAV_ITEMS.map(({ href, icon: Icon, label }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          const isNotif = href === "/notifications";
          return (
            <Link
              key={href}
              href={href}
              className={`
                flex items-center gap-3 px-3 py-3 rounded-xl
                font-medium text-sm transition-all duration-150
                ${active
                  ? "bg-accent-primary/10 text-accent-primary"
                  : "text-text-secondary hover:bg-surface-primary hover:text-text-primary"
                }
              `}
            >
              <span className="relative shrink-0">
                <Icon size={22} />
                {isNotif && unreadCount > 0 && (
                  <span className="
                    absolute -top-1.5 -right-1.5
                    bg-accent-error text-white text-2xs font-bold
                    rounded-full min-w-[16px] h-4 flex items-center justify-center px-0.5
                  ">
                    {unreadCount > 9 ? "9+" : unreadCount}
                  </span>
                )}
              </span>
              <span className="hidden lg:block">{label}</span>
            </Link>
          );
        })}

        {/* Profile link */}
        {did && (
          <Link
            href={`/profile/${encodeURIComponent(did)}`}
            className={`
              flex items-center gap-3 px-3 py-3 rounded-xl
              font-medium text-sm transition-all duration-150
              ${pathname.startsWith("/profile")
                ? "bg-accent-primary/10 text-accent-primary"
                : "text-text-secondary hover:bg-surface-primary hover:text-text-primary"
              }
            `}
          >
            <User size={22} className="shrink-0" />
            <span className="hidden lg:block">Profile</span>
          </Link>
        )}
      </nav>

      {/* Compose button */}
      <Link
        href="/posts/create"
        className="
          hidden lg:flex items-center justify-center gap-2
          bg-accent-primary hover:bg-accent-primary/90
          text-white font-semibold text-sm
          px-4 py-3 rounded-full
          transition-all duration-150 active:scale-95
          mb-4
        "
      >
        <PenSquare size={16} />
        Post
      </Link>
      {/* Mobile compose (icon only) */}
      <Link
        href="/posts/create"
        className="
          lg:hidden flex items-center justify-center
          bg-accent-primary hover:bg-accent-primary/90
          text-white
          w-10 h-10 rounded-full mx-auto
          transition-all duration-150
          mb-4
        "
      >
        <PenSquare size={18} />
      </Link>

      {/* Account strip */}
      {session && (
        <div className="flex items-center gap-3 px-2 py-3 rounded-xl hover:bg-surface-primary transition-colors group">
          <div className="
            w-9 h-9 rounded-full
            bg-gradient-to-br from-accent-primary to-accent-secondary
            flex items-center justify-center
            text-white font-bold text-sm shrink-0
          ">
            {(name ?? "?")[0].toUpperCase()}
          </div>
          <div className="hidden lg:flex flex-col min-w-0 flex-1">
            <span className="text-sm font-semibold text-text-primary truncate">{name}</span>
            <span className="text-xs text-text-tertiary truncate">
              {did?.split(":").pop()}
            </span>
          </div>
          <button
            onClick={() => signOut({ callbackUrl: "/explore" })}
            className="hidden lg:block text-text-quaternary hover:text-accent-error transition-colors ml-auto"
            title="Sign out"
          >
            <LogOut size={16} />
          </button>
        </div>
      )}
    </aside>
  );
}
