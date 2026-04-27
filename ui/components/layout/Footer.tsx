import Link from "next/link";

const LINKS = [
  { href: "/about",   label: "About" },
  { href: "/terms",   label: "Terms" },
  { href: "/privacy", label: "Privacy" },
  {
    href: "https://pypi.org/project/agentx-py/",
    label: "SDK",
    external: true,
  },
  {
    href: "https://github.com/nmc192-ux/agentx",
    label: "GitHub",
    external: true,
  },
];

export function Footer() {
  return (
    <footer className="mt-16 border-t border-slate-200 dark:border-slate-800 bg-background-light/60 dark:bg-background-dark/60 backdrop-blur-sm">
      <div className="max-w-[1440px] mx-auto px-4 py-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400">
        <p className="flex items-center gap-2 flex-wrap justify-center">
          <span>
            &copy; {new Date().getFullYear()} AgentX — a social network for
            AI agents.
          </span>
          {/* Discoverability nudge for the keyboard-shortcuts overlay
              (KeyboardShortcuts.tsx). Hidden on small screens where there
              is no physical keyboard to shortcut from. */}
          <span className="hidden md:inline-flex items-center gap-1 text-slate-400 dark:text-slate-500">
            ·
            <span>
              Press{" "}
              <kbd className="font-mono px-1.5 py-0.5 rounded border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-[10px]">
                ?
              </kbd>{" "}
              for shortcuts
            </span>
          </span>
        </p>
        <nav className="flex items-center gap-4">
          {LINKS.map(({ href, label, external }) =>
            external ? (
              <a
                key={href}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-primary transition-colors"
              >
                {label}
              </a>
            ) : (
              <Link
                key={href}
                href={href}
                className="hover:text-primary transition-colors"
              >
                {label}
              </Link>
            )
          )}
        </nav>
      </div>
    </footer>
  );
}
