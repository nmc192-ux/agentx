"use client";
/**
 * Sets the Sentry user context to the logged-in agent's DID on mount.
 * Rendered as a leaf node in the root layout — no visual output.
 */
import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";
import { getDid, isLoggedIn } from "@/lib/auth";

export function SentryUserProvider() {
  useEffect(() => {
    if (isLoggedIn()) {
      const did = getDid();
      if (did) {
        Sentry.setUser({ id: did });
      }
    } else {
      // Clear any stale user context after logout.
      Sentry.setUser(null);
    }
  }, []);

  return null;
}
