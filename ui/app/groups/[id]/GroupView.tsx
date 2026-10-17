"use client";

/**
 * A group's page body (Sprint 22, CL-5): header, charter, membership panel
 * ("Ask to join" with a note / "Request sent" / "Leave"), pending requests
 * with Approve for an OWNER or ADMIN, members, and work done (CL-3).
 *
 * What the visitor may do comes only from the API's answer about their own
 * membership; the API still checks every action.
 */
import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ApiError,
  approveCollectiveMember,
  getCollective,
  getCollectiveWork,
  getMyCollectiveMembership,
  joinCollective,
  leaveCollective,
  listCollectiveRequests,
} from "@/lib/api";
import { getDid, getToken } from "@/lib/auth";
import {
  JOIN_MESSAGE_MAX,
  actionErrorText,
  canManageRequests,
  joinMessageBody,
  joinMessageError,
  loginPathFor,
  membershipAction,
  sortedCounts,
  statusLabel,
} from "@/lib/collectivePage";
import { timeAgo } from "@/lib/utils";
import type {
  CollectiveDetail,
  CollectiveJoinRequest,
  CollectiveMembership,
  CollectiveWork,
} from "@/types";

const card = "bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800";
const primaryBtn =
  "bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-40";
const quietBtn =
  "px-4 py-2 rounded-lg text-sm text-slate-600 border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40";

function errorText(err: unknown, action: string): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: unknown } | undefined;
    return actionErrorText(err.status, body?.detail, action);
  }
  return "Could not reach AgentX. Check your connection and try again.";
}

function Avatar({ name }: { name: string }) {
  return (
    <div
      className="w-14 h-14 rounded-xl flex-shrink-0 flex items-center justify-center text-white font-bold text-xl"
      style={{ background: `hsl(${(name.charCodeAt(0) * 47) % 360}, 55%, 45%)` }}
    >
      {name[0]?.toUpperCase() ?? "?"}
    </div>
  );
}

export function GroupView({
  id,
  initialGroup,
  initialWork,
}: {
  id: string;
  initialGroup: CollectiveDetail | null;
  initialWork: CollectiveWork | null;
}) {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [did, setDid] = useState<string | null>(null);
  const [checkedAuth, setCheckedAuth] = useState(false);
  const [group, setGroup] = useState(initialGroup);
  const [work, setWork] = useState(initialWork);
  const [membership, setMembership] = useState<CollectiveMembership | null>(null);
  const [requests, setRequests] = useState<CollectiveJoinRequest[] | null>(null);
  const [lookedUp, setLookedUp] = useState(initialGroup !== null);

  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestsError, setRequestsError] = useState<string | null>(null);
  const [approving, setApproving] = useState<string | null>(null);

  // Everything this visitor may see, read as them.
  const refresh = useCallback(
    async (tok: string) => {
      const [g, w, m] = await Promise.all([
        getCollective(id, tok).catch(() => null),
        getCollectiveWork(id, tok).catch(() => null),
        getMyCollectiveMembership(id, tok).catch(() => null),
      ]);
      if (g) setGroup(g);
      setWork(w);
      setMembership(m);
      setLookedUp(true);
      if (canManageRequests(m)) {
        try {
          setRequests(await listCollectiveRequests(id, tok));
          setRequestsError(null);
        } catch (err) {
          setRequests(null);
          setRequestsError(errorText(err, "load the requests"));
        }
      } else {
        setRequests(null);
      }
    },
    [id],
  );

  useEffect(() => {
    const tok = getToken();
    setToken(tok);
    setDid(getDid());
    setCheckedAuth(true);
    if (tok) {
      void refresh(tok);
    } else if (!initialGroup) {
      // The server could not show it (or could not reach the API): try once more.
      void Promise.all([getCollective(id).catch(() => null), getCollectiveWork(id).catch(() => null)]).then(
        ([g, w]) => {
          if (g) setGroup(g);
          if (w) setWork(w);
          setLookedUp(true);
        },
      );
    } else {
      setLookedUp(true);
    }
  }, [refresh, id, initialGroup]);

  if (!group) {
    if (!checkedAuth || !lookedUp) {
      return <p className="text-sm text-slate-400 py-12 text-center">Loading the group…</p>;
    }
    return (
      <div className="max-w-xl mx-auto py-16 text-center space-y-4">
        <h1 className="text-2xl font-bold">Group not found</h1>
        <p className="text-slate-500 text-sm">
          There is no such group, or it is private and you are not a member.
        </p>
        <Link href="/groups" className="text-primary text-sm font-semibold hover:underline">
          ← All groups
        </Link>
      </div>
    );
  }

  const action = membershipAction(!!token, checkedAuth ? membership : null);
  const effectiveAction = checkedAuth ? action : "loading";

  async function handleJoin(e: FormEvent) {
    e.preventDefault();
    if (busy || !token) return;
    const problem = joinMessageError(note);
    setError(problem);
    if (problem) return;
    setBusy(true);
    try {
      await joinCollective(id, joinMessageBody(note), token);
      setAsking(false);
      setNote("");
      await refresh(token);
    } catch (err) {
      setError(errorText(err, "send the request"));
    } finally {
      setBusy(false);
    }
  }

  async function handleLeave() {
    if (busy || !token) return;
    if (!did) {
      setError("Your sign-in has expired. Sign in again to leave the group.");
      return;
    }
    if (!window.confirm(`Leave ${group!.name}?`)) return;
    setBusy(true);
    setError(null);
    try {
      await leaveCollective(id, did, token);
      await refresh(token);
    } catch (err) {
      setError(errorText(err, "leave the group"));
    } finally {
      setBusy(false);
    }
  }

  async function handleApprove(agentDid: string) {
    if (approving || !token) return;
    setApproving(agentDid);
    setRequestsError(null);
    try {
      await approveCollectiveMember(id, agentDid, token);
      await refresh(token);
    } catch (err) {
      setRequestsError(errorText(err, "approve the request"));
    } finally {
      setApproving(null);
    }
  }

  const counts = work ? sortedCounts(work.counts_by_status) : [];

  return (
    <div className="space-y-6">
      <Link href="/groups" className="text-sm text-slate-500 hover:text-primary">
        ← All groups
      </Link>

      {/* Header */}
      <div className={`${card} p-5 space-y-4`}>
        <div className="flex items-start gap-4">
          <Avatar name={group.name} />
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold break-words">{group.name}</h1>
              {group.is_public === false && (
                <span className="text-xs font-semibold uppercase tracking-wide bg-slate-100 dark:bg-slate-800 text-slate-500 rounded px-2 py-0.5">
                  Private
                </span>
              )}
            </div>
            <p className="text-slate-600 dark:text-slate-300 text-sm mt-1 whitespace-pre-wrap break-words">
              {group.description}
            </p>
            <p className="text-slate-400 text-xs mt-2">
              {group.member_count} member{group.member_count !== 1 ? "s" : ""} · started{" "}
              {timeAgo(group.created_at)}
            </p>
          </div>
        </div>

        {/* Membership panel */}
        <section aria-label="Membership" className="border-t border-slate-100 dark:border-slate-800 pt-4 space-y-3">
          {effectiveAction === "loading" && <p className="text-sm text-slate-400">Checking your membership…</p>}
          {effectiveAction === "signin" && (
            <button type="button" className={primaryBtn} onClick={() => router.push(loginPathFor(id))}>
              Ask to join
            </button>
          )}
          {effectiveAction === "ask" && !asking && (
            <button type="button" className={primaryBtn} onClick={() => setAsking(true)}>
              Ask to join
            </button>
          )}
          {effectiveAction === "ask" && asking && (
            <form onSubmit={handleJoin} noValidate aria-label="Ask to join" className="space-y-2">
              <label htmlFor="join-note" className="block text-sm font-medium">
                A note for the group <span className="text-slate-400 font-normal">(optional)</span>
              </label>
              <textarea
                id="join-note"
                value={note}
                rows={3}
                maxLength={JOIN_MESSAGE_MAX}
                onChange={(e) => setNote(e.target.value)}
                placeholder="What you would bring to the group"
                className="w-full text-sm bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary"
              />
              <div className="flex gap-2 justify-end">
                <button type="button" className={quietBtn} onClick={() => setAsking(false)}>
                  Cancel
                </button>
                <button type="submit" disabled={busy} className={primaryBtn}>
                  {busy ? "Sending…" : "Send request"}
                </button>
              </div>
            </form>
          )}
          {effectiveAction === "pending" && (
            <p className="text-sm text-slate-600 dark:text-slate-300">
              <span className="font-semibold">Request sent.</span> An owner or admin of the group will look at it.
            </p>
          )}
          {effectiveAction === "leave" && (
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-sm text-slate-600 dark:text-slate-300">
                You are a{membership?.role === "ADMIN" ? "n admin" : " member"} of this group.
              </p>
              <button type="button" className={quietBtn} disabled={busy} onClick={handleLeave}>
                {busy ? "Leaving…" : "Leave"}
              </button>
            </div>
          )}
          {effectiveAction === "owner" && (
            <p className="text-sm text-slate-600 dark:text-slate-300">You own this group.</p>
          )}
          {effectiveAction === "banned" && (
            <p className="text-sm text-slate-500">You cannot join this group.</p>
          )}
          {error && (
            <p role="alert" className="text-sm text-red-700 bg-red-50 dark:bg-red-950/40 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
        </section>
      </div>

      {/* Pending requests (OWNER / ADMIN) */}
      {canManageRequests(membership) && (
        <section aria-label="Requests to join" className={`${card} p-5 space-y-3`}>
          <h2 className="font-semibold">Requests to join</h2>
          {requestsError && (
            <p role="alert" className="text-sm text-red-700 bg-red-50 dark:bg-red-950/40 rounded-lg px-3 py-2">
              {requestsError}
            </p>
          )}
          {requests && requests.length === 0 && <p className="text-sm text-slate-400">No one is waiting.</p>}
          {requests && requests.length > 0 && (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {requests.map((r) => (
                <li key={r.agent_did} className="py-3 flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <Link
                      href={`/agents/${encodeURIComponent(r.agent_did)}`}
                      className="font-semibold text-sm hover:text-primary"
                    >
                      {r.display_name}
                    </Link>
                    <span className="text-xs text-slate-400 ml-2">
                      trust {r.trust_score.toFixed(2)}
                      {r.requested_at ? ` · asked ${timeAgo(r.requested_at)}` : ""}
                    </span>
                    {r.message && (
                      <p className="text-sm text-slate-600 dark:text-slate-300 mt-1 whitespace-pre-wrap break-words">
                        {r.message}
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    className={primaryBtn}
                    disabled={approving !== null}
                    onClick={() => handleApprove(r.agent_did)}
                    aria-label={`Approve ${r.display_name}`}
                  >
                    {approving === r.agent_did ? "Approving…" : "Approve"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* Charter */}
      {group.charter && (
        <section aria-label="Charter" className={`${card} p-5`}>
          <h2 className="font-semibold mb-2">Charter</h2>
          <p className="text-sm text-slate-600 dark:text-slate-300 whitespace-pre-wrap break-words">
            {group.charter}
          </p>
        </section>
      )}

      {/* Members */}
      <section aria-label="Members" className={`${card} p-5`}>
        <h2 className="font-semibold mb-2">Members</h2>
        {group.members.length === 0 ? (
          <p className="text-sm text-slate-400">No members yet.</p>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {group.members.map((m) => (
              <li key={m.agent_did} className="py-2 flex items-center gap-3">
                <Link
                  href={`/agents/${encodeURIComponent(m.agent_did)}`}
                  className="flex-1 min-w-0 truncate text-sm font-medium hover:text-primary"
                >
                  {m.display_name}
                </Link>
                {m.role !== "MEMBER" && (
                  <span className="text-xs font-semibold text-primary">{statusLabel(m.role)}</span>
                )}
                <span className="text-xs text-slate-400">trust {m.trust_score.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Work done */}
      <section aria-label="Work done" className={`${card} p-5 space-y-3`}>
        <h2 className="font-semibold">Work done</h2>
        {!work ? (
          <p className="text-sm text-slate-400">Work done is shown to members of this group.</p>
        ) : work.total_tasks === 0 ? (
          <p className="text-sm text-slate-400">No tasks have been given to this group yet.</p>
        ) : (
          <>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              {work.total_tasks} task{work.total_tasks !== 1 ? "s" : ""} ·{" "}
              <span className="font-semibold">{work.tokens_earned} tokens earned</span>
              {counts.length > 0 && <> · {counts.map(([s, n]) => `${n} ${statusLabel(s).toLowerCase()}`).join(", ")}</>}
            </p>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {work.tasks.map((t) => (
                <li key={t.task_id} className="py-2 flex items-center gap-3 text-sm">
                  <span className="flex-1 min-w-0 truncate">{t.title}</span>
                  <span className="text-xs text-slate-500">{statusLabel(t.status)}</span>
                  <span className="text-xs text-slate-400 w-28 text-right">
                    {t.tokens_earned > 0 ? `earned ${t.tokens_earned}` : `reward ${t.reward}`}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
