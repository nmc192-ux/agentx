/**
 * Static pages listed in sitemap.xml (Layer 1 plan, S1-3). Kept as plain data,
 * free of imports, so `npm test` can check that no hidden layer is listed.
 * app/sitemap.ts filters it through `visibleItems` with the layer flags.
 */

import type { MetadataRoute } from "next";

type Freq = NonNullable<MetadataRoute.Sitemap[number]["changeFrequency"]>;

export interface SitemapPath {
  href: string;
  changeFrequency: Freq;
  priority: number;
}

// /me is a client-only redirect and /messages /settings /notifications all
// auth-gate, so none of those go in. Pages in a hidden layer (lib/layers.ts)
// stay listed here and are dropped while their flag is off.
export const SITEMAP_PATHS: readonly SitemapPath[] = [
  { href: "/",             changeFrequency: "hourly",  priority: 1.0 },
  { href: "/welcome",      changeFrequency: "monthly", priority: 0.9 },
  { href: "/join",         changeFrequency: "monthly", priority: 0.8 },
  { href: "/agents",       changeFrequency: "daily",   priority: 0.8 },
  { href: "/explore",      changeFrequency: "daily",   priority: 0.7 },
  { href: "/trending",     changeFrequency: "hourly",  priority: 0.7 },
  { href: "/leaderboard",  changeFrequency: "daily",   priority: 0.7 },
  { href: "/activity",     changeFrequency: "hourly",  priority: 0.7 },
  { href: "/tags",         changeFrequency: "daily",   priority: 0.6 },
  { href: "/stats",        changeFrequency: "daily",   priority: 0.6 },
  { href: "/capabilities", changeFrequency: "daily",   priority: 0.6 },
  { href: "/services",     changeFrequency: "daily",   priority: 0.6 },
  { href: "/communities",  changeFrequency: "daily",   priority: 0.5 },
  { href: "/governance",   changeFrequency: "daily",   priority: 0.5 },
  { href: "/rooms",        changeFrequency: "daily",   priority: 0.5 },
  { href: "/about",        changeFrequency: "monthly", priority: 0.5 },
  { href: "/terms",        changeFrequency: "yearly",  priority: 0.3 },
  { href: "/privacy",      changeFrequency: "yearly",  priority: 0.3 },
  { href: "/login",        changeFrequency: "yearly",  priority: 0.4 },
];
