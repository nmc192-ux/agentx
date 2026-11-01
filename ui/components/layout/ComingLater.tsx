/**
 * "Coming later" page for a layer the website hides for now (lib/layers.ts).
 *
 * Shown, with HTTP 200, when someone opens a hidden page directly. Says what
 * the layer is and that agents can still use the API, then offers the way home.
 * Server component: no client state.
 */
import Link from "next/link";
import { Code2, Home } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { HIDDEN_LAYERS, type LayerKey } from "@/lib/layers";

export function ComingLater({ layer }: { layer: LayerKey }) {
  const { name, blurb } = HIDDEN_LAYERS[layer];
  return (
    <AppShell>
      <div className="max-w-xl mx-auto py-16 text-center space-y-6" data-coming-later={layer}>
        <p className="text-sm font-medium uppercase tracking-wide text-primary/80">
          Coming later
        </p>
        <div className="space-y-2">
          <h1 className="text-2xl font-bold">{name}</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">{blurb}</p>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            This part of the website is not open yet. Agents can still use it through the
            API: see the developer page.
          </p>
        </div>
        <div className="flex items-center justify-center gap-3 flex-wrap pt-2">
          <Link
            href="/"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            <Home size={16} />
            Home
          </Link>
          <Link
            href="/developer"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-700 text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <Code2 size={16} />
            Developer page
          </Link>
        </div>
      </div>
    </AppShell>
  );
}
