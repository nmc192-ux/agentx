import { AppShell } from "./AppShell";

/**
 * Shared shell for static content pages: /terms, /privacy, /about, /cookies.
 * Applies a readable prose width and a consistent header. Body content is
 * passed as children and may use plain HTML headings / paragraphs; the
 * ancestor `.legal-prose` class supplies typography.
 */
export function LegalPage({
  title,
  updated,
  children,
}: {
  title: string;
  updated: string;
  children: React.ReactNode;
}) {
  return (
    <AppShell>
      <article className="legal-prose mx-auto max-w-3xl">
        <header className="mb-8 border-b border-slate-200 dark:border-slate-800 pb-4">
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            {title}
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Last updated: {updated}
          </p>
        </header>
        <div className="space-y-5 text-slate-700 dark:text-slate-300 leading-relaxed [&>h2]:text-xl [&>h2]:font-semibold [&>h2]:text-slate-900 [&>h2]:dark:text-slate-100 [&>h2]:mt-8 [&>h2]:mb-3 [&>h3]:text-base [&>h3]:font-semibold [&>h3]:mt-6 [&>h3]:mb-2 [&>ul]:list-disc [&>ul]:pl-6 [&>ul]:space-y-1 [&>ol]:list-decimal [&>ol]:pl-6 [&>ol]:space-y-1 [&>p]:leading-relaxed [&_a]:text-primary [&_a:hover]:underline">
          {children}
        </div>
      </article>
    </AppShell>
  );
}
