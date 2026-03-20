"use client";
import { FormEvent, useState } from "react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function ComposeBox() {
  const [to, setTo]           = useState("");
  const [msg, setMsg]         = useState("");
  const [sending, setSending] = useState(false);
  const [flash, setFlash]     = useState<"sent" | "error" | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!to.trim() || !msg.trim() || sending) return;

    const token    = typeof window !== "undefined" ? localStorage.getItem("agentx_token") : null;
    const senderDid = typeof window !== "undefined" ? localStorage.getItem("agentx_did") ?? "did:agentx:ui-user" : "did:agentx:ui-user";

    setSending(true);
    setFlash(null);
    try {
      const r = await fetch(`${BASE}/messages/send`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          sender_agent_did:   senderDid,
          receiver_agent_did: to.trim(),
          message:            msg.trim(),
        }),
      });
      if (!r.ok) throw new Error(`${r.status}`);
      setTo("");
      setMsg("");
      setFlash("sent");
      setTimeout(() => setFlash(null), 2_000);
    } catch {
      setFlash("error");
      setTimeout(() => setFlash(null), 3_000);
    } finally {
      setSending(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-center gap-2 px-4 py-2 border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
    >
      <input
        value={to}
        onChange={(e) => setTo(e.target.value)}
        placeholder="To: did:agentx:…"
        className="w-52 text-xs bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
      />
      <input
        value={msg}
        onChange={(e) => setMsg(e.target.value)}
        placeholder="Message…"
        className="flex-1 text-xs bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
      />
      <button
        type="submit"
        disabled={sending || !to.trim() || !msg.trim()}
        className="text-xs font-semibold px-4 py-2 rounded-lg bg-primary text-white disabled:opacity-40 hover:opacity-90 transition-opacity"
      >
        {sending ? "…" : "Send"}
      </button>
      {flash === "sent" && <span className="text-xs text-green-500 whitespace-nowrap">Sent!</span>}
      {flash === "error" && <span className="text-xs text-red-500 whitespace-nowrap">Failed</span>}
    </form>
  );
}
