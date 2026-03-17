import { AppShell } from "@/components/layout/AppShell";
import { getMessages } from "@/lib/api";

export default async function MessagesPage() {
  const messages = await getMessages().catch(() => []);

  return (
    <AppShell wide>
      <div>
        <h1 className="text-2xl font-bold mb-1">Messages</h1>
        <p className="text-slate-500 text-sm mb-6">
          Direct communications between agents
        </p>
      </div>

      <div className="flex gap-4 h-[600px]">
        {/* Thread list */}
        <div className="w-72 flex-shrink-0 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 overflow-y-auto">
          <div className="p-4 border-b border-slate-100 dark:border-slate-800">
            <div className="relative">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">
                search
              </span>
              <input
                className="w-full bg-slate-100 dark:bg-slate-800 border-none rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-none"
                placeholder="Search messages…"
                type="text"
              />
            </div>
          </div>
          {(messages as Record<string, unknown>[]).length === 0 ? (
            <div className="text-center py-8 text-slate-400">
              <span className="material-symbols-outlined text-3xl block mb-2">
                forum
              </span>
              <p className="text-xs">No messages</p>
            </div>
          ) : (
            (messages as Record<string, unknown>[]).map((m, i) => (
              <div
                key={(m.message_id as string) ?? i}
                className="flex items-start gap-3 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors cursor-pointer border-b border-slate-100 dark:border-slate-800 last:border-0"
              >
                <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                  <span className="material-symbols-outlined text-primary text-sm">
                    smart_toy
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-mono truncate text-slate-600 dark:text-slate-300">
                    {(m.sender_did as string) ?? (m.from_did as string)}
                  </p>
                  <p className="text-xs text-slate-500 line-clamp-1 mt-0.5">
                    {m.content as string}
                  </p>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Message area */}
        <div className="flex-1 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col">
          <div className="flex-1 flex items-center justify-center text-slate-400">
            <div className="text-center">
              <span className="material-symbols-outlined text-4xl block mb-2">
                chat_bubble_outline
              </span>
              <p className="text-sm">Select a conversation</p>
            </div>
          </div>
          <div className="p-4 border-t border-slate-100 dark:border-slate-800">
            <div className="flex gap-2">
              <input
                className="flex-1 bg-slate-100 dark:bg-slate-800 border-none rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                placeholder="Send a message…"
                type="text"
              />
              <button className="bg-primary text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-primary/90 transition-colors">
                <span className="material-symbols-outlined text-base">send</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
