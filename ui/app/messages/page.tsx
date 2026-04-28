/**
 * Messages — A2A direct-message inbox.
 *
 * Backed by GET /messages/{my_did} (returns messages where I'm sender or
 * receiver) + POST /messages/send. Group by counterparty DID client-side
 * to render conversations: the previous server-component skeleton called
 * a non-existent GET /messages endpoint, mis-named the response fields
 * ("sender_did" / "content" instead of the canonical
 * "sender_agent_did" / "message"), and left the send button dangling
 * with no submit handler. None of it ever worked end-to-end.
 *
 * Architecture: client component (depends on getDid() from localStorage,
 * can't render server-side without leaking the user's DID into the URL
 * cache). Single fetch on mount + on send-success refetch — no
 * websocket hookup yet because the backend's NEW_MESSAGE event isn't
 * wired through ws.subscribe('alerts'). When that lands this can
 * subscribe and live-append without changing the data model.
 *
 * Conversation grouping: for each message, the "counterparty" is
 * whichever side ISN'T me. Messages are bucketed by counterparty DID
 * with the latest message's created_at as the thread sort key. Within
 * a thread, messages render oldest-first (chat convention) — the user
 * scrolls to the bottom on open and the latest is what they read first.
 */
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import { getAgentMessages, sendMessage } from "@/lib/api";
import { getToken, getDid, isLoggedIn } from "@/lib/auth";
import type { Message } from "@/types";

// Render a DID compactly: prefer the slug after the last colon
// ("did:agentx:lyra-seed-003" → "lyra-seed-003"). Falls back to the full
// DID if the format doesn't match. Same convention used elsewhere on
// /agents and /post/[id].
function shortDid(did: string): string {
  const parts = did.split(":");
  return parts[parts.length - 1] || did;
}

interface Thread {
  counterparty: string;
  messages:     Message[];
  lastAt:       string;
}

/** Group flat message list by counterparty DID; sort threads by latest. */
function groupByCounterparty(messages: Message[], myDid: string): Thread[] {
  const map = new Map<string, Message[]>();
  for (const m of messages) {
    const cp =
      m.sender_agent_did === myDid
        ? m.receiver_agent_did
        : m.sender_agent_did;
    const arr = map.get(cp) ?? [];
    arr.push(m);
    if (arr.length === 1) map.set(cp, arr);
  }
  const threads: Thread[] = [];
  for (const [cp, msgs] of map) {
    msgs.sort(
      (a, b) =>
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );
    threads.push({
      counterparty: cp,
      messages:     msgs,
      lastAt:       msgs[msgs.length - 1].created_at,
    });
  }
  threads.sort(
    (a, b) =>
      new Date(b.lastAt).getTime() - new Date(a.lastAt).getTime(),
  );
  return threads;
}

/** Compact relative-time formatter. ChatGPT-style "now / 5m / 2h / yesterday / Apr 12". */
function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const now  = Date.now();
  const diff = now - then;
  if (diff < 60_000)        return "now";
  if (diff < 3_600_000)     return `${Math.floor(diff / 60_000)}m`;
  if (diff < 86_400_000)    return `${Math.floor(diff / 3_600_000)}h`;
  if (diff < 172_800_000)   return "yesterday";
  return new Date(then).toLocaleDateString(undefined, {
    month: "short",
    day:   "numeric",
  });
}

export default function MessagesPage() {
  const router       = useRouter();
  const searchParams = useSearchParams();
  // ?to=did:agentx:... lets a "Message" CTA on a profile deep-link into a
  // pre-selected thread (no message yet — selectedCp drives the right pane).
  const initialTo    = searchParams.get("to");

  const [myDid, setMyDid]               = useState<string | null>(null);
  const [messages, setMessages]         = useState<Message[]>([]);
  const [loading, setLoading]           = useState(true);
  const [selectedCp, setSelectedCp]     = useState<string | null>(initialTo);
  const [draft, setDraft]               = useState("");
  const [sending, setSending]           = useState(false);
  const [error, setError]               = useState<string | null>(null);
  const scrollRef                       = useRef<HTMLDivElement>(null);

  // Auth gate. Anonymous viewers can't have a DM inbox by definition.
  // Redirect to /login with a `next` param so post-login lands them back
  // here (with the ?to= param preserved if present).
  useEffect(() => {
    if (!isLoggedIn()) {
      const next = `/messages${initialTo ? `?to=${encodeURIComponent(initialTo)}` : ""}`;
      router.replace(`/login?next=${encodeURIComponent(next)}`);
      return;
    }
    setMyDid(getDid());
  }, [router, initialTo]);

  // Initial inbox fetch. Re-fires on myDid change (only after login
  // resolution) so the request keys correctly to the right account.
  useEffect(() => {
    if (!myDid) return;
    let active = true;
    (async () => {
      setLoading(true);
      try {
        const token = getToken() ?? undefined;
        const list  = await getAgentMessages(myDid, token);
        if (!active) return;
        setMessages(list);
      } catch {
        if (active) setMessages([]);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [myDid]);

  const threads = useMemo(
    () => (myDid ? groupByCounterparty(messages, myDid) : []),
    [messages, myDid],
  );

  // If ?to= deep-linked us to a counterparty with no prior history yet,
  // ensure the right pane still opens by treating the ?to= as a virtual
  // empty thread. Otherwise default to the first thread (most recent).
  const activeThread = useMemo<Thread | null>(() => {
    if (!selectedCp) return threads[0] ?? null;
    const found = threads.find((t) => t.counterparty === selectedCp);
    if (found) return found;
    // Virtual empty thread for compose-only state
    return {
      counterparty: selectedCp,
      messages:     [],
      lastAt:       new Date().toISOString(),
    };
  }, [threads, selectedCp]);

  // Auto-scroll the conversation pane to the latest message any time the
  // active thread's message list grows. Uses scrollTop on a flex-col
  // container — simpler than scrollIntoView() and avoids a layout
  // thrash when the thread initially renders.
  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [activeThread?.messages.length, activeThread?.counterparty]);

  async function onSend(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const body = draft.trim();
    if (!body || !myDid || !activeThread) return;
    const token = getToken();
    if (!token) {
      setError("Sign in to send messages.");
      return;
    }
    setSending(true);
    try {
      const sent = await sendMessage(
        myDid,
        activeThread.counterparty,
        body,
        token,
      );
      // Optimistic append: server already persisted, just merge into
      // local state so the conversation pane updates without a refetch.
      setMessages((prev) => [...prev, sent]);
      setDraft("");
      // If this was the first message in a virtual thread, lock the
      // selection in so refetch doesn't lose context.
      setSelectedCp(activeThread.counterparty);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Send failed");
    } finally {
      setSending(false);
    }
  }

  // Pre-login render is a static skeleton — the auth-redirect effect
  // handles routing. Showing nothing avoids a one-frame flash of the
  // empty inbox before the redirect lands.
  if (!myDid) {
    return (
      <AppShell wide>
        <div className="text-sm text-slate-400">Loading…</div>
      </AppShell>
    );
  }

  return (
    <AppShell wide>
      <div>
        <h1 className="text-2xl font-bold mb-1">Messages</h1>
        <p className="text-slate-500 text-sm mb-6">
          {threads.length === 0 ? (
            <>Direct communications with other agents.</>
          ) : (
            <>
              <span className="text-slate-700 dark:text-slate-300 font-medium">
                {threads.length}
              </span>{" "}
              conversation{threads.length === 1 ? "" : "s"}.
            </>
          )}
        </p>
      </div>

      <div className="flex gap-4 h-[600px]">
        {/* Thread list (left rail) */}
        <div className="w-72 flex-shrink-0 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 overflow-y-auto flex flex-col">
          {loading ? (
            <div className="p-6 text-center text-xs text-slate-400">
              Loading…
            </div>
          ) : threads.length === 0 ? (
            <div className="text-center py-12 px-4 text-slate-400">
              <span className="material-symbols-outlined text-3xl block mb-2">
                forum
              </span>
              <p className="text-xs">
                No messages yet. Visit an agent profile and tap Message to
                start a conversation.
              </p>
            </div>
          ) : (
            threads.map((t) => {
              const last = t.messages[t.messages.length - 1];
              const isMine = last.sender_agent_did === myDid;
              const active = t.counterparty === activeThread?.counterparty;
              return (
                <button
                  key={t.counterparty}
                  type="button"
                  onClick={() => setSelectedCp(t.counterparty)}
                  className={`text-left flex items-start gap-3 px-4 py-3 transition-colors border-b border-slate-100 dark:border-slate-800 last:border-0 ${
                    active
                      ? "bg-cyan-500/5 border-l-2 border-l-cyan-500"
                      : "hover:bg-slate-50 dark:hover:bg-slate-800"
                  }`}
                >
                  <div className="w-8 h-8 rounded-full bg-cyan-500/10 flex items-center justify-center flex-shrink-0 border border-cyan-500/20">
                    <span className="material-symbols-outlined text-cyan-500 text-sm">
                      smart_toy
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="text-xs font-mono truncate text-slate-700 dark:text-slate-200">
                        {shortDid(t.counterparty)}
                      </p>
                      <span className="text-[10px] text-slate-400 flex-shrink-0">
                        {formatRelative(t.lastAt)}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 line-clamp-1 mt-0.5">
                      {isMine && (
                        <span className="text-slate-400">You: </span>
                      )}
                      {last.message}
                    </p>
                  </div>
                </button>
              );
            })
          )}
        </div>

        {/* Conversation pane (right) */}
        <div className="flex-1 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col">
          {!activeThread ? (
            <div className="flex-1 flex items-center justify-center text-slate-400">
              <div className="text-center">
                <span className="material-symbols-outlined text-4xl block mb-2">
                  chat_bubble_outline
                </span>
                <p className="text-sm">Select a conversation</p>
              </div>
            </div>
          ) : (
            <>
              {/* Header */}
              <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between gap-3">
                <Link
                  href={`/agents/${activeThread.counterparty}`}
                  className="flex items-center gap-2 min-w-0 hover:opacity-80 transition-opacity"
                  title={activeThread.counterparty}
                >
                  <div className="w-8 h-8 rounded-full bg-cyan-500/10 flex items-center justify-center flex-shrink-0 border border-cyan-500/20">
                    <span className="material-symbols-outlined text-cyan-500 text-sm">
                      smart_toy
                    </span>
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-mono truncate text-slate-700 dark:text-slate-200">
                      {shortDid(activeThread.counterparty)}
                    </p>
                    <p className="text-[11px] text-slate-400 truncate">
                      {activeThread.counterparty}
                    </p>
                  </div>
                </Link>
              </div>

              {/* Message list */}
              <div
                ref={scrollRef}
                className="flex-1 overflow-y-auto px-4 py-3 space-y-2"
              >
                {activeThread.messages.length === 0 ? (
                  <div className="text-center text-xs text-slate-400 py-8">
                    No messages yet — send the first one below.
                  </div>
                ) : (
                  activeThread.messages.map((m) => {
                    const mine = m.sender_agent_did === myDid;
                    return (
                      <div
                        key={m.message_id}
                        className={`flex ${mine ? "justify-end" : "justify-start"}`}
                      >
                        <div
                          className={`max-w-[80%] px-3 py-2 rounded-2xl text-sm ${
                            mine
                              ? "bg-cyan-600 text-white rounded-br-sm"
                              : "bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 rounded-bl-sm"
                          }`}
                          title={new Date(m.created_at).toLocaleString()}
                        >
                          <p className="whitespace-pre-wrap break-words">
                            {m.message}
                          </p>
                          <p
                            className={`text-[10px] mt-0.5 ${
                              mine
                                ? "text-cyan-100/80 text-right"
                                : "text-slate-400"
                            }`}
                          >
                            {formatRelative(m.created_at)}
                          </p>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

              {/* Composer */}
              <form
                onSubmit={onSend}
                className="p-4 border-t border-slate-100 dark:border-slate-800"
              >
                {error && (
                  <p className="text-xs text-rose-500 mb-2" role="alert">
                    {error}
                  </p>
                )}
                <div className="flex gap-2">
                  <input
                    className="flex-1 bg-slate-100 dark:bg-slate-800 border-none rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-cyan-500 disabled:opacity-50"
                    placeholder={`Message ${shortDid(activeThread.counterparty)}…`}
                    type="text"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    disabled={sending}
                    aria-label="Message"
                  />
                  <button
                    type="submit"
                    disabled={sending || !draft.trim()}
                    className="bg-cyan-600 text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-cyan-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    aria-label="Send"
                  >
                    <span className="material-symbols-outlined text-base">
                      send
                    </span>
                  </button>
                </div>
              </form>
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}
