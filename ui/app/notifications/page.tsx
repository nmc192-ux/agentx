import { AppShell } from "@/components/layout/AppShell";
import { NotificationsClient } from "./NotificationsClient";

export const dynamic = "force-dynamic";

export default function NotificationsPage() {
  return (
    <AppShell>
      <NotificationsClient />
    </AppShell>
  );
}
