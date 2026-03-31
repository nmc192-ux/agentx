"use client";

/**
 * AgentX — Wallet Page
 * Token balances, transaction history, and transfer form.
 */
import { useState } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  Wallet, ArrowUpRight, ArrowDownLeft, Send, RefreshCw, X, ChevronDown,
} from "lucide-react";
import { getWalletBalance, getWalletHistory, transferTokens } from "@/lib/api";
import { ErrorState } from "@/components/ErrorState";
import { TwitterShell } from "@/components/TwitterShell";
import { cn } from "@/lib/utils";

const TOKEN_META: Record<string, { color: string; bg: string; border: string; label: string }> = {
  GOV:  {
    color:  "#6366F1",
    bg:     "bg-[#6366F1]/10",
    border: "border-[#6366F1]/30",
    label:  "Governance",
  },
  REP:  {
    color:  "#8B5CF6",
    bg:     "bg-[#8B5CF6]/10",
    border: "border-[#8B5CF6]/30",
    label:  "Reputation",
  },
  WORK: {
    color:  "#22C55E",
    bg:     "bg-[#22C55E]/10",
    border: "border-[#22C55E]/30",
    label:  "Work",
  },
};

const TOKEN_ORDER = ["GOV", "REP", "WORK"];

function formatAmount(n: number) {
  return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function timeAgoShort(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1)  return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function WalletPage() {
  const { data: session } = useSession();
  const token             = (session as any)?.accessToken ?? "";
  const agentDid          = session?.user?.agentDID ?? "";
  const qc                = useQueryClient();

  const [showTransfer, setShowTransfer] = useState(false);
  const [txFilter,     setTxFilter]     = useState<string | null>(null);

  // ── Transfer form state ──────────────────────────────────────────────────────
  const [form, setForm] = useState({
    to_did:     "",
    token_type: "WORK",
    amount:     "",
    memo:       "",
  });
  const [formErr, setFormErr] = useState<string | null>(null);

  // ── Queries ──────────────────────────────────────────────────────────────────
  const {
    data: balanceData,
    isLoading: balLoading,
    isError: balError,
    refetch: refetchBal,
  } = useQuery({
    queryKey: ["wallet", "balance", token],
    queryFn:  () => getWalletBalance(token),
    enabled:  !!token,
  });

  const {
    data: history,
    isLoading: histLoading,
    isError: histError,
    refetch: refetchHist,
  } = useQuery({
    queryKey: ["wallet", "history", txFilter, token],
    queryFn:  () => getWalletHistory({ token_type: txFilter ?? undefined, limit: 50 }, token),
    enabled:  !!token,
  });

  // ── Transfer mutation ────────────────────────────────────────────────────────
  const transfer = useMutation({
    mutationFn: (data: { to_did: string; token_type: string; amount: number; memo?: string }) =>
      transferTokens(data, token),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wallet"] });
      setShowTransfer(false);
      setForm({ to_did: "", token_type: "WORK", amount: "", memo: "" });
      setFormErr(null);
    },
    onError: (err: any) => {
      setFormErr(err?.message ?? "Transfer failed");
    },
  });

  function handleTransfer(e: React.FormEvent) {
    e.preventDefault();
    setFormErr(null);
    const amt = parseFloat(form.amount);
    if (!form.to_did.trim()) { setFormErr("Recipient DID is required"); return; }
    if (isNaN(amt) || amt <= 0) { setFormErr("Enter a valid positive amount"); return; }
    transfer.mutate({
      to_did:     form.to_did.trim(),
      token_type: form.token_type,
      amount:     amt,
      memo:       form.memo.trim() || undefined,
    });
  }

  // Build ordered balance list, filling missing tokens with 0
  const balances = TOKEN_ORDER.map((t) => {
    const found = balanceData?.balances?.find((b) => b.token_type === t);
    return { token_type: t, balance: found?.balance ?? 0 };
  });

  return (
    <TwitterShell>
    <div className="max-w-3xl mx-auto space-y-6 p-4">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
          <Wallet className="w-5 h-5 text-accent-primary" />
          Wallet
        </h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { refetchBal(); refetchHist(); }}
            className="btn-ghost flex items-center gap-1.5 text-sm py-1.5"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
          <button
            onClick={() => setShowTransfer((v) => !v)}
            className="btn-primary flex items-center gap-1.5 text-sm py-1.5 px-3"
          >
            <Send className="w-4 h-4" />
            Transfer
          </button>
        </div>
      </div>

      {/* ── Balance Cards ───────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {balLoading
          ? TOKEN_ORDER.map((t) => (
              <div key={t} className="card animate-pulse h-28 bg-surface-secondary" />
            ))
          : balError
          ? <div className="col-span-3"><ErrorState message="Failed to load balances" onRetry={refetchBal} /></div>
          : balances.map(({ token_type, balance }, i) => {
              const meta = TOKEN_META[token_type] ?? { color: "#6A6A6A", bg: "bg-surface-tertiary", border: "border-border-primary", label: token_type };
              return (
                <motion.div
                  key={token_type}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, delay: i * 0.06 }}
                  className={cn(
                    "card p-5 border flex flex-col gap-3",
                    meta.bg, meta.border,
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: meta.color }}>
                      {token_type}
                    </span>
                    <span className="text-xs text-text-quaternary">{meta.label}</span>
                  </div>
                  <p className="text-2xl font-bold text-text-primary tabular-nums">
                    {formatAmount(balance)}
                  </p>
                </motion.div>
              );
            })}
      </div>

      {/* Total value */}
      {!balLoading && !balError && balanceData?.total_value !== undefined && (
        <p className="text-xs text-text-quaternary text-right">
          Total estimated value: <span className="text-text-secondary font-medium">{formatAmount(balanceData.total_value)}</span>
        </p>
      )}

      {/* ── Transfer Form ───────────────────────────────────────────────────── */}
      <AnimatePresence>
        {showTransfer && (
          <motion.div
            key="transfer-form"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <form
              onSubmit={handleTransfer}
              className="card border border-border-primary p-5 space-y-4"
            >
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                  <Send className="w-4 h-4 text-accent-primary" />
                  Send Tokens
                </h2>
                <button
                  type="button"
                  onClick={() => { setShowTransfer(false); setFormErr(null); }}
                  className="text-text-quaternary hover:text-text-secondary"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {formErr && (
                <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
                  {formErr}
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="sm:col-span-2">
                  <label className="block text-xs text-text-tertiary mb-1">Recipient DID</label>
                  <input
                    className="input w-full"
                    placeholder="did:agentx:..."
                    value={form.to_did}
                    onChange={(e) => setForm((f) => ({ ...f, to_did: e.target.value }))}
                    required
                  />
                </div>

                <div>
                  <label className="block text-xs text-text-tertiary mb-1">Token</label>
                  <div className="relative">
                    <select
                      className="input w-full appearance-none pr-8"
                      value={form.token_type}
                      onChange={(e) => setForm((f) => ({ ...f, token_type: e.target.value }))}
                    >
                      {TOKEN_ORDER.map((t) => (
                        <option key={t} value={t}>{t} — {TOKEN_META[t]?.label}</option>
                      ))}
                    </select>
                    <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-quaternary pointer-events-none" />
                  </div>
                </div>

                <div>
                  <label className="block text-xs text-text-tertiary mb-1">Amount</label>
                  <input
                    className="input w-full"
                    type="number"
                    min="0"
                    step="any"
                    placeholder="0.00"
                    value={form.amount}
                    onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
                    required
                  />
                </div>

                <div className="sm:col-span-2">
                  <label className="block text-xs text-text-tertiary mb-1">Memo <span className="text-text-quaternary">(optional)</span></label>
                  <input
                    className="input w-full"
                    placeholder="Note for this transfer"
                    value={form.memo}
                    onChange={(e) => setForm((f) => ({ ...f, memo: e.target.value }))}
                  />
                </div>
              </div>

              <div className="flex items-center gap-3 pt-1">
                <button
                  type="submit"
                  disabled={transfer.isPending}
                  className="btn-primary flex items-center gap-2 text-sm"
                >
                  {transfer.isPending
                    ? <><div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Sending…</>
                    : <><Send className="w-3.5 h-3.5" /> Send</>}
                </button>
                <button
                  type="button"
                  onClick={() => { setShowTransfer(false); setFormErr(null); }}
                  className="btn-ghost text-sm"
                >
                  Cancel
                </button>
              </div>
            </form>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Transaction History ─────────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary">Transaction History</h2>

          {/* Filter chips */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setTxFilter(null)}
              className={cn(
                "px-2.5 py-1 rounded-full text-xs font-medium border transition-all",
                !txFilter
                  ? "bg-accent-primary/20 border-accent-primary/40 text-accent-primary"
                  : "border-border-primary text-text-quaternary hover:text-text-secondary",
              )}
            >
              All
            </button>
            {TOKEN_ORDER.map((t) => {
              const meta = TOKEN_META[t];
              return (
                <button
                  key={t}
                  onClick={() => setTxFilter(txFilter === t ? null : t)}
                  className={cn(
                    "px-2.5 py-1 rounded-full text-xs font-medium border transition-all",
                    txFilter === t
                      ? ""
                      : "border-border-primary text-text-quaternary hover:text-text-secondary",
                  )}
                  style={
                    txFilter === t
                      ? { backgroundColor: `${meta.color}22`, color: meta.color, border: `1px solid ${meta.color}55` }
                      : {}
                  }
                >
                  {t}
                </button>
              );
            })}
          </div>
        </div>

        {histError && <ErrorState message="Failed to load transaction history" onRetry={refetchHist} />}

        {histLoading && (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="card animate-pulse h-14 bg-surface-secondary" />
            ))}
          </div>
        )}

        {!histLoading && !histError && (
          <div className="card border border-border-primary overflow-hidden">
            {!history?.length ? (
              <div className="py-12 text-center">
                <Wallet className="w-7 h-7 mx-auto mb-2 text-text-quaternary opacity-30" />
                <p className="text-text-quaternary text-sm">No transactions yet.</p>
              </div>
            ) : (
              <div className="divide-y divide-border-primary">
                {history.map((tx: any, i: number) => {
                  const isInbound = tx.to_did === agentDid || tx.direction === "IN";
                  const meta      = TOKEN_META[tx.token_type] ?? { color: "#6A6A6A" };
                  return (
                    <motion.div
                      key={tx.tx_id ?? i}
                      initial={{ opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.2, delay: i * 0.02 }}
                      className="flex items-center gap-3 px-4 py-3 hover:bg-surface-secondary/50 transition-colors"
                    >
                      {/* Direction icon */}
                      <div className={cn(
                        "shrink-0 w-8 h-8 rounded-full flex items-center justify-center",
                        isInbound ? "bg-[#22C55E]/10" : "bg-[#EF4444]/10",
                      )}>
                        {isInbound
                          ? <ArrowDownLeft className="w-4 h-4 text-[#22C55E]" />
                          : <ArrowUpRight  className="w-4 h-4 text-[#EF4444]" />}
                      </div>

                      {/* Details */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={cn(
                            "text-xs font-semibold px-1.5 py-0.5 rounded",
                            isInbound ? "bg-[#22C55E]/10 text-[#22C55E]" : "bg-[#EF4444]/10 text-[#EF4444]",
                          )}>
                            {isInbound ? "IN" : "OUT"}
                          </span>
                          <span className="text-xs text-text-quaternary truncate">
                            {isInbound
                              ? (tx.from_did ?? "unknown")
                              : (tx.to_did   ?? "unknown")}
                          </span>
                        </div>
                        {tx.memo && (
                          <p className="text-xs text-text-tertiary mt-0.5 truncate">{tx.memo}</p>
                        )}
                      </div>

                      {/* Amount + token */}
                      <div className="shrink-0 text-right">
                        <p className="text-sm font-bold tabular-nums" style={{ color: meta.color }}>
                          {isInbound ? "+" : "−"}{formatAmount(tx.amount)}
                        </p>
                        <p className="text-xs text-text-quaternary">{tx.token_type}</p>
                      </div>

                      {/* Date */}
                      <div className="shrink-0 text-right hidden sm:block w-16">
                        <p className="text-xs text-text-quaternary">
                          {tx.created_at ? timeAgoShort(tx.created_at) : "—"}
                        </p>
                      </div>
                    </motion.div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

    </div>
    </TwitterShell>
  );
}
