"use client";

/**
 * AgentX — EmptyState
 *
 * One reusable component to replace the "No posts yet" / "No followers
 * yet" / "No notifications" dead-end paragraphs scattered across the
 * app. Every empty state is now an opportunity: an icon, a one-line
 * headline, a softer subline, and zero-or-more CTAs that take the user
 * somewhere productive.
 *
 * Designed for the inside-of-card use case (no outer chrome of its own
 * — the parent supplies the card / panel border). Works in both light
 * and dark themes thanks to the slate-* palette already used elsewhere.
 *
 * Usage:
 *   <EmptyState
 *     icon={<MessageSquare />}
 *     title="No posts yet"
 *     subtitle="Be the first to share something."
 *     primary={{ label: "Open Explore", href: "/explore" }}
 *     secondary={{ label: "Trending tags", href: "/explore#trending" }}
 *   />
 */
import type { ReactNode } from "react";
import Link from "next/link";

interface CTA {
  label:    string;
  href?:    string;
  onClick?: () => void;
}

interface Props {
  icon?:     ReactNode;
  title:     string;
  subtitle?: string;
  primary?:   CTA;
  secondary?: CTA;
  /** Optional extra className applied to the outer wrapper. */
  className?: string;
}

function CTAButton({ cta, variant }: { cta: CTA; variant: "primary" | "secondary" }) {
  const className =
    variant === "primary"
      ? "inline-flex items-center justify-center px-4 py-1.5 rounded-full text-xs font-semibold bg-cyan-600 text-white hover:bg-cyan-500 transition-colors"
      : "inline-flex items-center justify-center px-4 py-1.5 rounded-full text-xs font-medium text-slate-300 hover:text-slate-100 hover:bg-slate-800 transition-colors";

  if (cta.href) {
    return (
      <Link href={cta.href} className={className}>
        {cta.label}
      </Link>
    );
  }
  return (
    <button type="button" onClick={cta.onClick} className={className}>
      {cta.label}
    </button>
  );
}

export function EmptyState({
  icon,
  title,
  subtitle,
  primary,
  secondary,
  className = "",
}: Props) {
  return (
    <div className={`flex flex-col items-center justify-center text-center py-10 px-4 ${className}`}>
      {icon && (
        <div className="mb-3 text-slate-500 [&>svg]:w-8 [&>svg]:h-8 opacity-60">
          {icon}
        </div>
      )}
      <p className="text-sm font-medium text-slate-200">{title}</p>
      {subtitle && (
        <p className="text-xs text-slate-500 mt-1 max-w-xs">{subtitle}</p>
      )}
      {(primary || secondary) && (
        <div className="flex items-center gap-2 mt-4">
          {primary   && <CTAButton cta={primary}   variant="primary"   />}
          {secondary && <CTAButton cta={secondary} variant="secondary" />}
        </div>
      )}
    </div>
  );
}
