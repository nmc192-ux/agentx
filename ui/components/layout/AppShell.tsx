import { TopNav } from "./TopNav";
import { Sidebar } from "./Sidebar";

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
        <main className={`flex-1 py-8 space-y-6 ${wide ? "" : "max-w-4xl"}`}>
          {children}
        </main>
      </div>
    </div>
  );
}
