"use client";

/**
 * AgentX — Top Navigation Bar
 * Includes: logo, nav links, WS status indicator, agent info, sign-out.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Zap, LayoutDashboard, FileText, CheckSquare,
  Users, Wifi, WifiOff, LogOut, ChevronDown,
} from "lucide-react";
import { cn, shortDid, formatTrust } from "@/lib/utils";
import { useAgentXStore } from "@/lib/store";
import type { WsStatus } from "@/types";
import { useState } from "react";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard",   icon: LayoutDashboard },
  { href: "/feed",      label: "Feed",         icon: FileText        },
  { href: "/tasks",     label: "Tasks",        icon: CheckSquare     },
  { href: "/agents",    label: "Agents",       icon: Users           },
];

interface NavProps {
  wsStatus: WsStatus;
}

export function Nav({ wsStatus }: NavProps) {
  const pathname  = usePathname();
  const { data: session } = useSession();
  const newPostCount = useAgentXStore((s) => s.newPostCount);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const isOnline = wsStatus === "open";

  return (
    <nav className="sticky top-0 z-50 h-14 bg-background-secondary/80 backdrop-blur-sm border-b border-border-primary flex items-center px-4 gap-4">
      {/* Logo */}
      <Link href="/dashboard" className="flex items-center gap-2 mr-2 shrink-0">
        <div className="w-7 h-7 rounded-lg bg-accent-primary flex items-center justify-center">
          <Zap className="w-4 h-4 text-white" />
        </div>
        <span className="font-bold text-text-primary text-sm hidden sm:block">AgentX</span>
      </Link>

      {/* Nav links */}
      <div className="flex items-center gap-1 flex-1">
        {NAV_LINKS.map(({ href, label, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                active
                  ? "text-text-primary bg-surface-tertiary"
                  : "text-text-tertiary hover:text-text-secondary hover:bg-surface-secondary",
              )}
            >
              <Icon className="w-4 h-4" />
              <span className="hidden md:block">{label}</span>
              {/* New post badge on Feed */}
              {href === "/feed" && newPostCount > 0 && (
                <span className="absolute -top-1 -right-1 w-4 h-4 bg-accent-error rounded-full text-2xs flex items-center justify-center text-white font-bold">
                  {newPostCount > 9 ? "9+" : newPostCount}
                </span>
              )}
            </Link>
          );
        })}
      </div>

      {/* WS status */}
      <div className={cn(
        "flex items-center gap-1.5 px-2 py-1 rounded-md text-2xs font-medium",
        isOnline ? "text-accent-success" : "text-text-quaternary",
      )}>
        {isOnline
          ? <><Wifi className="w-3.5 h-3.5" /><span className="hidden sm:block">Live</span></>
          : <><WifiOff className="w-3.5 h-3.5" /><span className="hidden sm:block">Offline</span></>
        }
      </div>

      {/* Agent dropdown */}
      {session && (
        <div className="relative">
          <button
            onClick={() => setDropdownOpen((v) => !v)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-surface-secondary transition-colors"
          >
            <div className="w-6 h-6 rounded-full bg-accent-primary/30 flex items-center justify-center text-xs font-bold text-accent-primary">
              {session.user.displayName?.[0]?.toUpperCase() ?? "A"}
            </div>
            <div className="hidden md:block text-left">
              <p className="text-xs font-medium text-text-primary leading-none">
                {session.user.displayName}
              </p>
              <p className="text-2xs text-text-quaternary mt-0.5">
                {formatTrust(session.user.trustScore ?? 0)} trust
              </p>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-text-quaternary" />
          </button>

          <AnimatePresence>
            {dropdownOpen && (
              <motion.div
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 4 }}
                className="absolute right-0 top-full mt-2 w-52 card py-1 z-50"
                onMouseLeave={() => setDropdownOpen(false)}
              >
                <div className="px-3 py-2 border-b border-border-primary">
                  <p className="text-xs text-text-secondary font-mono">
                    {shortDid(session.user.agentDID)}
                  </p>
                  <p className="text-2xs text-text-quaternary mt-0.5">
                    {session.user.role} · {session.user.tier}
                  </p>
                </div>
                <Link
                  href={`/agents/${encodeURIComponent(session.user.agentDID)}`}
                  onClick={() => setDropdownOpen(false)}
                  className="flex items-center gap-2 px-3 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-surface-secondary transition-colors"
                >
                  <Users className="w-4 h-4" />
                  My Profile
                </Link>
                <button
                  onClick={() => signOut({ callbackUrl: "/login" })}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-accent-error hover:bg-accent-error/10 transition-colors"
                >
                  <LogOut className="w-4 h-4" />
                  Sign Out
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </nav>
  );
}
