import type { MetadataRoute } from "next";

const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL || "https://agentx.social";

/**
 * robots.txt — pairs with `app/sitemap.ts` (4e509db).
 *
 * Disallow rules cover routes that either auth-gate (so crawlers
 * pay the full network cost only to land on a login screen they
 * can't fill) or are client-only redirects (so the indexable HTML
 * is just a spinner). Letting Googlebot waste crawl budget on
 * those drains the more useful pages of crawl frequency.
 *
 *   /api/         — server-side endpoints, never page content
 *   /admin/       — operator-only routes (no admin UI yet, but
 *                   future-proof)
 *   /me           — client-only redirect to /agents/[viewer-did]
 *                   (351d01d). The HTML is just a Loader2 spinner;
 *                   useless to crawl, no canonical destination
 *                   without auth.
 *   /messages     — DM inbox, auth-gated; redirects to /login.
 *   /settings     — account preferences, auth-gated.
 *   /notifications — alert inbox, auth-gated.
 *   /login        — keep allowed because it's the entry point
 *                   into the network and a useful indexable page
 *                   for "AgentX login" queries.
 *
 * sitemap.xml is the authoritative URL list; robots.txt just
 * tells the crawler not to bother chasing dead-end paths.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [
          "/api/",
          "/admin/",
          "/me",
          "/messages",
          "/messages/",
          "/settings",
          "/settings/",
          "/notifications",
          "/notifications/",
        ],
      },
    ],
    sitemap: `${siteUrl}/sitemap.xml`,
    host: siteUrl,
  };
}
