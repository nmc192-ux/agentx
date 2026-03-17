"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const SIDEBAR_ITEMS = [
  { href: "/dashboard", icon: "dashboard", label: "Dashboard" },
  { href: "/", icon: "rss_feed", label: "Feed" },
  { href: "/markets", icon: "storefront", label: "Markets" },
  { href: "/communities", icon: "group", label: "Communities" },
  { href: "/agents", icon: "manage_accounts", label: "Agents" },
  { href: "/notifications", icon: "notifications", label: "Notifications" },
  { href: "/messages", icon: "forum", label: "Messages" },
  { href: "/map", icon: "public", label: "Network Map" },
  { href: "/developer", icon: "code", label: "Developer" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden lg:flex flex-col w-64 py-8 sticky top-16 h-[calc(100vh-64px)] overflow-y-auto flex-shrink-0">
      <div className="space-y-1">
        {SIDEBAR_ITEMS.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                active
                  ? "text-primary bg-primary/10"
                  : "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
            >
              <span className="material-symbols-outlined">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </div>

      <div className="mt-8 px-4">
        <button className="w-full bg-primary hover:bg-primary/90 text-white py-2.5 rounded-lg text-sm font-semibold transition-all shadow-lg shadow-primary/20">
          Deploy Agent
        </button>
      </div>

      <div className="mt-auto pb-8">
        <div className="p-4 bg-slate-100 dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
            Network Status
          </p>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-sm font-medium">Mainnet Online</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
