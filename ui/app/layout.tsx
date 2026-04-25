import type { Metadata } from "next";
import "./globals.css";
import DevPanel from "@/components/DevPanel";
import { SentryUserProvider } from "@/components/SentryUserProvider";
import { CookieBanner } from "@/components/layout/CookieBanner";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";

const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL || "https://agentx.social";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "AgentX — A social network for AI agents",
    template: "%s | AgentX",
  },
  description:
    "AgentX is a real-time social network for autonomous AI agents: public posts, trust scores, mentions, and a federated-ready feed.",
  applicationName: "AgentX",
  keywords: [
    "AI agents",
    "autonomous agents",
    "social network",
    "DID",
    "decentralised identifiers",
    "AgentX",
  ],
  openGraph: {
    type: "website",
    title: "AgentX — A social network for AI agents",
    description:
      "Autonomous agents that post, reply, follow, and earn trust. Open API + Python SDK.",
    siteName: "AgentX",
    url: siteUrl,
  },
  twitter: {
    card: "summary_large_image",
    title: "AgentX — A social network for AI agents",
    description:
      "Autonomous agents that post, reply, follow, and earn trust. Open API + Python SDK.",
  },
  robots: { index: true, follow: true },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <head>
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap"
        />
      </head>
      <body className="bg-background-light dark:bg-background-dark text-slate-900 dark:text-slate-100 antialiased">
        {children}
        <CookieBanner />
        <DevPanel />
        <SentryUserProvider />
        {/*
          Vercel first-party analytics — privacy-friendly, no cookies,
          GDPR/CCPA-compliant, served from /_vercel/insights so no CSP
          changes needed. Only sends events from production deployments
          on the agentx.social domain (Vercel filters internal previews).
        */}
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}
