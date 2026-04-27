/**
 * Root suspense boundary.
 *
 * Picked up by Next.js whenever a server component above suspends —
 * shows a centered spinner inside the standard AppShell so the page
 * chrome is visible while data is loading. Without this, Next falls
 * back to a totally blank screen.
 */
import { Loader2 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";

export default function Loading() {
  return (
    <AppShell>
      <div
        className="flex flex-col items-center justify-center py-20 gap-3 text-slate-500"
        role="status"
        aria-live="polite"
      >
        <Loader2 className="animate-spin text-primary" size={28} />
        <p className="text-xs uppercase tracking-wider">Loading…</p>
      </div>
    </AppShell>
  );
}
