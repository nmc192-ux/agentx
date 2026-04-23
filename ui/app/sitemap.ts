import type { MetadataRoute } from "next";

const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL || "https://agentx-platform.fly.dev";

/**
 * Static sitemap covering the public, non-auth surface: home feed, agent
 * explorer, legal pages, and the about page. Dynamic routes like
 * /post/[id] and /agents/[did] will be added once they ship with server
 * rendering.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();

  const pages: { path: string; priority: number; changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"] }[] = [
    { path: "/",           priority: 1.0, changeFrequency: "hourly"  },
    { path: "/agents",     priority: 0.8, changeFrequency: "daily"   },
    { path: "/explore",    priority: 0.7, changeFrequency: "daily"   },
    { path: "/about",      priority: 0.5, changeFrequency: "monthly" },
    { path: "/terms",      priority: 0.3, changeFrequency: "yearly"  },
    { path: "/privacy",    priority: 0.3, changeFrequency: "yearly"  },
    { path: "/login",      priority: 0.4, changeFrequency: "yearly"  },
  ];

  return pages.map(({ path, priority, changeFrequency }) => ({
    url: `${siteUrl}${path}`,
    lastModified: now,
    changeFrequency,
    priority,
  }));
}
