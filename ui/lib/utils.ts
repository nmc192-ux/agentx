/**
 * AgentX ui/ — Utility helpers
 * Migrated from frontend/src/lib/utils.ts (Step 3.1 consolidation).
 */
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes safely */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format trust score 0-1 as percentage string */
export function formatTrust(score: number): string {
  return `${Math.round(score * 100)}%`;
}

/** Truncate a DID for display: "did:agentx:nova-001" → "nova-001" */
export function shortDid(did: string): string {
  return did.split(":").pop() ?? did;
}

/** Format ISO date as "Mar 7, 2026" */
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day:   "numeric",
    year:  "numeric",
  });
}

/** Format ISO date as "2 hours ago" */
export function timeAgo(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  const intervals: [number, string][] = [
    [31536000, "year"],
    [2592000,  "month"],
    [604800,   "week"],
    [86400,    "day"],
    [3600,     "hour"],
    [60,       "minute"],
  ];
  for (const [secs, label] of intervals) {
    const count = Math.floor(seconds / secs);
    if (count >= 1) return `${count} ${label}${count > 1 ? "s" : ""} ago`;
  }
  return "just now";
}

/** Clamp a number between min and max */
export function clamp(n: number, min: number, max: number): number {
  return Math.min(Math.max(n, min), max);
}
