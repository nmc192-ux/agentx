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

/**
 * Shared focus-visible ring for footer links — keyboard-only (silent
 * for mouse). Mirrors the TopNav `NAV_FOCUS` pattern so the global
 * chrome (top + bottom of every page) presents a consistent focus
 * indicator as users tab through the layout.
 *
 * `rounded` gives the ring corners on plain text links that don't
 * otherwise have a border-radius. Cyan-500/60 matches the AgentX
 * brand color used elsewhere on global-chrome elements.
 */
const FOOTER_FOCUS =
  "rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/60";

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
                className={`hover:text-primary transition-colors ${FOOTER_FOCUS}`}
              >
                {label}
              </a>
            ) : (
              <Link
                key={href}
                href={href}
                className={`hover:text-primary transition-colors ${FOOTER_FOCUS}`}
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
