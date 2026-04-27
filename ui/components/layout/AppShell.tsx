import { TopNav } from "./TopNav";
import { Sidebar } from "./Sidebar";
import { Footer } from "./Footer";
import { MobileBottomNav } from "./MobileBottomNav";
import { KeyboardShortcuts } from "./KeyboardShortcuts";

export function AppShell({
  children,
  wide = false,
}: {
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className="flex flex-col min-h-screen">
      <TopNav />
      <div className="flex flex-1 max-w-[1440px] mx-auto w-full px-4 gap-6">
        <Sidebar />
        {/* pb-20 on mobile so the sticky MobileBottomNav (h-14 + safe-area)
            doesn't cover the last bit of content. md+ keeps py-8 only. */}
        <main className={`flex-1 py-8 pb-20 md:pb-8 space-y-6 ${wide ? "" : "max-w-4xl"}`}>
          {children}
        </main>
      </div>
      <Footer />
      <MobileBottomNav />
      <KeyboardShortcuts />
    </div>
  );
}
