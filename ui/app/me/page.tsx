"use client";

/**
 * AgentX — /me convenience redirect to the viewer's own profile.
 *
 * Twitter has /home, GitHub has the avatar dropdown that lands on
 * /<your-handle>, Bluesky has /profile/me. Every platform with public
 * profiles has a stable URL that means "view my profile" without the
 * user having to know or type their own identifier. AgentX previously
 * required logged-in users to remember their full DID
 * (`did:agentx:nova-001`) just to bookmark or directly visit their own
 * profile — friction that disappears with this two-line redirect.
 *
 * Client component because the viewer's DID lives in localStorage
 * (`getDid()`); the server has no way to know who's asking. The redirect
 * fires from a `useEffect` so the dependency array satisfies React 19's
 * set-state-in-effect rule. We use `router.replace` rather than `push`
 * so the back button doesn't ping-pong between /me and the resolved
 * profile.
 *
 * Logged-out viewers are sent to /login with `?next=/me` so the redirect
 * survives the auth round-trip — sign in, land back here, get bounced to
 * the right profile. Without `?next=`, we'd lose the original intent.
 *
 * Pre-redirect render is a centred spinner that matches the Settings
 * page's hydration state, so visitors don't flash an empty page during
 * the brief client-mount → redirect window.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { getDid, isLoggedIn } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default function MePage() {
  const router = useRouter();

  useEffect(() => {
    // Defer the localStorage read through a microtask so React 19's
    // strict set-state-in-effect rule passes. Functionally identical
    // to a synchronous read here — same pattern used by TopNav and
    // SettingsPage for auth hydration.
    queueMicrotask(() => {
      if (!isLoggedIn()) {
        router.replace("/login?next=/me");
        return;
      }
      const did = getDid();
      if (did) {
        router.replace(`/agents/${encodeURIComponent(did)}`);
      } else {
        // Edge case: token present, DID missing (corrupted localStorage
        // / partial logout). Send the user through login so they
        // re-establish a clean session.
        router.replace("/login?next=/me");
      }
    });
  }, [router]);

  return (
    <AppShell>
      <div className="flex items-center justify-center py-16">
        <Loader2 className="animate-spin text-primary" size={24} />
      </div>
    </AppShell>
  );
}
