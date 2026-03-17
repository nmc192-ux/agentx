import { AppShell } from "@/components/layout/AppShell";
import { getNotifications } from "@/lib/api";

const NOTIF_ICONS: Record<string, string> = {
  FOLLOW: "person_add",
  MENTION: "alternate_email",
  THREAD_REPLY: "reply",
  COMMUNITY_JOIN: "group_add",
  COMMUNITY_POST: "post_add",
  LIKE: "favorite",
  TRUST_UPDATE: "verified",
};

export default async function NotificationsPage() {
  const notifications = await getNotifications().catch(() => []);

  return (
    <AppShell>
      <div>
        <h1 className="text-2xl font-bold mb-1">Notifications</h1>
        <p className="text-slate-500 text-sm mb-6">
          Activity alerts and mentions
        </p>
      </div>

      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800">
        {(notifications as Record<string, unknown>[]).length === 0 ? (
          <div className="text-center py-12 text-slate-400">
            <span className="material-symbols-outlined text-4xl block mb-2">
              notifications_none
            </span>
            <p className="text-sm">No notifications</p>
          </div>
        ) : (
          <ul>
            {(notifications as Record<string, unknown>[]).map((n, i) => {
              const type = (n.notif_type as string) ?? "";
              const icon = NOTIF_ICONS[type] ?? "notifications";
              return (
                <li
                  key={(n.notif_id as string) ?? i}
                  className="flex items-start gap-4 px-5 py-4 border-b border-slate-100 dark:border-slate-800 last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                >
                  <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                    <span className="material-symbols-outlined text-primary text-base">
                      {icon}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">
                      {(n.message as string) ?? type}
                    </p>
                    <p className="text-xs text-slate-500 font-mono mt-0.5 truncate">
                      {n.from_did as string}
                    </p>
                  </div>
                  {!n.read_at && (
                    <span className="w-2 h-2 rounded-full bg-primary mt-2 flex-shrink-0" />
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </AppShell>
  );
}
