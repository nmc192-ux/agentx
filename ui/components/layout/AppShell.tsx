import { TopNav } from "./TopNav";
import { Sidebar } from "./Sidebar";
import { Footer } from "./Footer";
import { MobileBottomNav } from "./MobileBottomNav";
import { KeyboardShortcuts } from "./KeyboardShortcuts";
import { CommandPalette } from "./CommandPalette";

/**
 * The app shell (Layer 1 plan, S2): left menu, middle page, right column.
 * `right` fills the right column (shown from `lg`); without it the middle
 * page takes the room. `wide` lets the middle page use all of it.
 */
export function AppShell({
  children,
  wide = false,
  right,
}: {
  children: React.ReactNode;
  wide?: boolean;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col min-h-screen">
      <TopNav searchInRightColumn={!!right} />
      <div className="flex flex-1 max-w-[1440px] mx-auto w-full px-4 gap-6">
        <Sidebar />
        {/* pb-20 on mobile so the sticky MobileBottomNav (h-14 + safe-area)
            doesn't cover the last bit of content. md+ keeps py-8 only. */}
        <main className={`flex-1 min-w-0 py-8 pb-20 md:pb-8 space-y-6 ${wide ? "" : "max-w-4xl"}`}>
          {children}
        </main>
        {right && (
          <aside className="hidden lg:flex flex-col gap-4 w-80 flex-shrink-0 py-8 sticky top-16 self-start max-h-[calc(100vh-64px)] overflow-y-auto">
            {right}
          </aside>
        )}
      </div>
      <Footer />
      <MobileBottomNav />
      <KeyboardShortcuts />
      <CommandPalette />
    </div>
  );
}
