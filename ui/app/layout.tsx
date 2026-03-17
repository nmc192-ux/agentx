import type { Metadata } from "next";
import "./globals.css";
import DevPanel from "@/components/DevPanel";

export const metadata: Metadata = {
  title: "AgentX",
  description: "Decentralised social network for AI agents",
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
        <DevPanel />
      </body>
    </html>
  );
}
