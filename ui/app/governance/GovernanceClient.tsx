"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Loader2, Search, X } from "lucide-react";
import { isLoggedIn, getToken } from "@/lib/auth";
import { castVote, createProposal, type Proposal } from "@/lib/api";
import { DebateView } from "@/components/governance/DebateView";

// ── Helpers ──────────────────────────────────────────────────────────────────

function relativeDeadline(dateStr: string): string {
  const diff = new Date(dateStr).getTime() - Date.now();
  if (diff <= 0) return "Ended";
  const hours = Math.floor(diff / 3_600_000);
  if (hours < 24) return `${hours}h remaining`;
  const days = Math.floor(hours / 24);
  return `${days}d remaining`;
}

function truncateDid(did: string): string {
  return did.length > 24 ? did.slice(0, 24) + "…" : did;
}

// ── Vote Bar ─────────────────────────────────────────────────────────────────

function VoteBar({ yes, no, abstain }: { yes: number; no: number; abstain: number }) {
  const total = yes + no + abstain || 1;
  const yesPct = (yes / total) * 100;
  const noPct = (no / total) * 100;
  const abstainPct = (abstain / total) * 100;

  return (
    <div className="space-y-1">
      <div className="h-2 rounded-full overflow-hidden bg-slate-800 flex">
        {yesPct > 0 && (
          <div className="bg-green-500 h-full" style={{ width: `${yesPct}%` }} />
        )}
        {noPct > 0 && (
          <div className="bg-red-500 h-full" style={{ width: `${noPct}%` }} />
        )}
        {abstainPct > 0 && (
          <div className="bg-slate-500 h-full" style={{ width: `${abstainPct}%` }} />
        )}
      </div>
      <p className="text-xs text-slate-500">
        <span className="text-green-400">&#10003; {yes}</span>
        {" · "}
        <span className="text-red-400">&#10007; {no}</span>
        {" · "}
        <span className="text-slate-400">&#8212; {abstain}</span>
      </p>
    </div>
  );
}

// ── Proposal Card ─────────────────────────────────────────────────────────────

function ProposalCard({
  proposal,
  voted,
  onVote,
}: {
  proposal: Proposal;
  voted: boolean;
  onVote: (id: string, vote: "yes" | "no" | "abstain") => Promise<void>;
}) {
  const [loading, setLoading] = useState<"yes" | "no" | "abstain" | null>(null);
  const [showDebate, setShowDebate] = useState(false);
  const loggedIn = isLoggedIn();

  const descPreview =
    proposal.description.length > 200
      ? proposal.description.slice(0, 200) + "..."
      : proposal.description;

  async function handleVote(v: "yes" | "no" | "abstain") {
    if (voted || loading) return;
    setLoading(v);
    try {
      await onVote(proposal.proposal_id, v);
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5 space-y-3 border-l-4 border-l-blue-500">
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-semibold text-sm leading-snug">{proposal.title}</h3>
        <span className="text-xs text-slate-500 whitespace-nowrap flex-shrink-0">
          {relativeDeadline(proposal.voting_ends_at)}
        </span>
      </div>

      <p className="text-sm text-slate-400">{descPreview}</p>

      <p className="text-xs text-slate-600 font-mono">
        Proposed by: {truncateDid(proposal.proposer_did)}
      </p>

      <VoteBar
        yes={proposal.yes_votes}
        no={proposal.no_votes}
        abstain={proposal.abstain_votes}
      />

      {loggedIn ? (
        <div className="flex items-center gap-2 pt-1">
          {(["yes", "no", "abstain"] as const).map((v) => {
            const isSpinning = loading === v;
            const disabled = voted || loading !== null;
            const styles: Record<string, string> = {
              yes: "border border-green-500/30 text-green-400 hover:bg-green-500/10 px-3 py-1 rounded text-sm transition-colors",
              no: "border border-red-500/30 text-red-400 hover:bg-red-500/10 px-3 py-1 rounded text-sm transition-colors",
              abstain: "border border-slate-600 text-slate-400 hover:bg-slate-800 px-3 py-1 rounded text-sm transition-colors",
            };
            const labels: Record<string, string> = {
              yes: "✓ Yes",
              no: "✗ No",
              abstain: "— Abstain",
            };
            return (
              <button
                key={v}
                onClick={() => handleVote(v)}
                disabled={disabled}
                className={`${styles[v]} flex items-center gap-1 disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                {isSpinning && <Loader2 className="w-3 h-3 animate-spin" />}
                {labels[v]}
              </button>
            );
          })}
          {voted && (
            <span className="text-xs text-slate-500 ml-1">Vote recorded</span>
          )}
          <button
            onClick={() => setShowDebate(!showDebate)}
            className="ml-auto text-xs text-slate-500 hover:text-cyan-400 transition-colors"
          >
            {showDebate ? "Hide Debate" : "View Debate"}
          </button>
        </div>
      ) : (
        <Link
          href="/login?next=/governance"
          className="text-xs text-slate-500 hover:text-primary"
        >
          Login to vote →
        </Link>
      )}

      {/* Enhanced Debate View */}
      {showDebate && (
        <div className="pt-3 border-t border-slate-800">
          <DebateView proposalId={proposal.proposal_id} />
        </div>
      )}
    </div>
  );
}

// ── Create Proposal Form ──────────────────────────────────────────────────────

function CreateProposalForm({ onCreated }: { onCreated: (p: Proposal) => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [votingDays, setVotingDays] = useState(3);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isLoggedIn()) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const token = getToken()!;
      const proposal = await createProposal(title, description, votingDays, token);
      onCreated(proposal);
      setOpen(false);
      setTitle("");
      setDescription("");
      setVotingDays(3);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create proposal");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-sm font-medium border border-slate-700 text-slate-300 hover:border-primary hover:text-primary px-4 py-2 rounded-lg transition-colors"
      >
        <span className="text-base leading-none">+</span>
        New Proposal
      </button>

      {open && (
        <form
          onSubmit={handleSubmit}
          className="rounded-xl border border-slate-800 bg-slate-900 p-5 space-y-4"
        >
          <h3 className="font-semibold text-sm">Create Proposal</h3>

          <div className="space-y-1">
            <label className="text-xs text-slate-400 font-medium">Title</label>
            <input
              required
              maxLength={120}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Short, descriptive title"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs text-slate-400 font-medium">Description</label>
            <textarea
              required
              minLength={20}
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Explain the proposal in detail (min 20 chars)"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary resize-none"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs text-slate-400 font-medium">Voting Period</label>
            <select
              value={votingDays}
              onChange={(e) => setVotingDays(Number(e.target.value))}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value={1}>1 day</option>
              <option value={3}>3 days</option>
              <option value={7}>7 days</option>
            </select>
          </div>

          {error && (
            <p className="text-xs text-red-400 bg-red-500/10 px-3 py-2 rounded-lg">
              {error}
            </p>
          )}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center gap-2 bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              {submitting && <Loader2 className="w-3 h-3 animate-spin" />}
              {submitting ? "Submitting…" : "Submit Proposal"}
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-sm text-slate-400 hover:text-slate-300 transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

// ── Main Client Component ─────────────────────────────────────────────────────

interface Props {
  initialProposals: Proposal[];
  results: Proposal[];
}

type ActiveSort = "newest" | "ending" | "votes";

const SORT_LABELS: { key: ActiveSort; label: string; title: string }[] = [
  { key: "newest", label: "Newest",      title: "Most recently created" },
  { key: "ending", label: "Ending soon", title: "Voting deadline ascending" },
  { key: "votes",  label: "Most votes",  title: "Total vote count descending" },
];

function totalVotes(p: Proposal): number {
  return (p.yes_votes ?? 0) + (p.no_votes ?? 0) + (p.abstain_votes ?? 0);
}

export function GovernanceClient({ initialProposals, results }: Props) {
  const [proposals, setProposals] = useState<Proposal[]>(initialProposals);
  const [voted, setVoted] = useState<Set<string>>(new Set());

  // Active-proposals filter state. Sibling pattern to the search+sort
  // strips already shipped on /agents (c20432a), /capabilities (425b63f),
  // /services (9c6249c), /communities (84243ea), and /rooms (06a8c2b).
  // Default sort is "newest" because that's the order the backend
  // already returns, so the strip is identity-on-first-render and
  // doesn't surprise visitors with a different ordering than they had
  // before this ship landed.
  const [query,      setQuery]      = useState("");
  const [activeSort, setActiveSort] = useState<ActiveSort>("newest");

  const visibleProposals = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = proposals.filter((p) => {
      if (!q) return true;
      return (
        p.title?.toLowerCase().includes(q) ||
        p.description?.toLowerCase().includes(q)
      );
    });
    const sorted = filtered.slice();
    if (activeSort === "newest") {
      sorted.sort((a, b) =>
        Date.parse(b.created_at) - Date.parse(a.created_at),
      );
    } else if (activeSort === "ending") {
      // Ending soon — closest deadline first. Past-deadline proposals
      // (voting_ends_at < now) sort to the end since the surface here
      // is "Active Proposals" and a past deadline is effectively a
      // tombstone the backend should have already moved to Results.
      sorted.sort((a, b) => {
        const ta = Date.parse(a.voting_ends_at) || Infinity;
        const tb = Date.parse(b.voting_ends_at) || Infinity;
        return ta - tb;
      });
    } else {
      sorted.sort((a, b) => totalVotes(b) - totalVotes(a));
    }
    return sorted;
  }, [proposals, query, activeSort]);

  const showFilterCount =
    query.trim().length > 0 || activeSort !== "newest";

  async function handleVote(proposalId: string, vote: "yes" | "no" | "abstain") {
    const token = getToken();
    if (!token) throw new Error("Not logged in.");
    await castVote(proposalId, vote, token);
    setVoted((prev) => new Set(prev).add(proposalId));
    // Optimistically bump the vote count in the list
    setProposals((prev) =>
      prev.map((p) => {
        if (p.proposal_id !== proposalId) return p;
        return {
          ...p,
          yes_votes:     vote === "yes"     ? p.yes_votes + 1     : p.yes_votes,
          no_votes:      vote === "no"      ? p.no_votes + 1      : p.no_votes,
          abstain_votes: vote === "abstain" ? p.abstain_votes + 1 : p.abstain_votes,
        };
      })
    );
  }

  function handleProposalCreated(proposal: Proposal) {
    setProposals((prev) => [proposal, ...prev]);
  }

  return (
    <div className="space-y-10">
      {/* Active Proposals */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Active Proposals</h2>

        {/* Filter strip — only render when there are >1 proposals so a
            cold-start dao doesn't pretend filterable content exists.
            Search input on top, sort chips below. */}
        {proposals.length > 1 && (
          <div className="flex flex-col gap-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" aria-hidden="true" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search proposals by title or description…"
                aria-label="Search proposals"
                className="w-full pl-9 pr-9 py-2 text-sm rounded-lg
                           bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700
                           focus:outline-none focus:ring-2 focus:ring-primary/40
                           placeholder:text-slate-400"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  aria-label="Clear search"
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md
                             text-slate-400 hover:text-slate-200 hover:bg-slate-700/40 transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            <div className="flex flex-wrap gap-x-5 gap-y-2 items-center">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] uppercase tracking-wide text-slate-500">Sort</span>
                <div className="flex gap-1">
                  {SORT_LABELS.map(({ key, label, title }) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setActiveSort(key)}
                      title={title}
                      aria-pressed={activeSort === key}
                      className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors
                                  ${activeSort === key
                                    ? "bg-primary text-white"
                                    : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"}`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {showFilterCount && (
                <span className="text-[11px] text-slate-500 ml-auto">
                  {visibleProposals.length} of {proposals.length}
                </span>
              )}
            </div>
          </div>
        )}

        {proposals.length === 0 ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-8 text-center">
            <p className="text-slate-500 text-sm">
              No active proposals yet. Create one below.
            </p>
          </div>
        ) : visibleProposals.length === 0 ? (
          // Filter narrowed to zero — distinct from the cold-start
          // empty state with a "Show all" escape so users never get
          // stuck staring at a no-match pane.
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-8 text-center">
            <p className="text-slate-500 text-sm mb-3">
              No proposals match this search.
            </p>
            <button
              type="button"
              onClick={() => { setQuery(""); setActiveSort("newest"); }}
              className="text-xs font-medium text-primary hover:text-primary/80 transition-colors"
            >
              Show all
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            {visibleProposals.map((p) => (
              <ProposalCard
                key={p.proposal_id}
                proposal={p}
                voted={voted.has(p.proposal_id)}
                onVote={handleVote}
              />
            ))}
          </div>
        )}
      </section>

      {/* Create Proposal */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Create Proposal</h2>
        <CreateProposalForm onCreated={handleProposalCreated} />
        {!isLoggedIn() && (
          <p className="text-xs text-slate-500">
            <Link
              href="/login?next=/governance"
              className="text-xs text-slate-500 hover:text-primary"
            >
              Login to vote →
            </Link>{" "}
            or submit a proposal.
          </p>
        )}
      </section>

      {/* Results */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Results</h2>
        {results.length === 0 ? (
          <p className="text-slate-500 text-sm">No completed proposals yet.</p>
        ) : (
          <div className="space-y-3">
            {results.map((p) => {
              const passed = p.yes_votes > p.no_votes;
              return (
                <div
                  key={p.proposal_id}
                  className={`rounded-xl border border-slate-800 bg-slate-900 p-5 space-y-3 border-l-4 ${
                    passed ? "border-l-green-500" : "border-l-red-500"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <h3 className="font-semibold text-sm flex-1">{p.title}</h3>
                    {passed ? (
                      <span className="bg-green-500/10 text-green-400 text-xs px-2 py-0.5 rounded-full whitespace-nowrap">
                        PASSED ✅
                      </span>
                    ) : (
                      <span className="bg-red-500/10 text-red-400 text-xs px-2 py-0.5 rounded-full whitespace-nowrap">
                        FAILED ❌
                      </span>
                    )}
                  </div>
                  <VoteBar
                    yes={p.yes_votes}
                    no={p.no_votes}
                    abstain={p.abstain_votes}
                  />
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
