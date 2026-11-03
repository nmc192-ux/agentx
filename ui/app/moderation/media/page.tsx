"use client";

/**
 * Image review (Layer 1 S4-10b), for FOUNDER / OPERATOR accounts only.
 *
 * Lists every PENDING image, oldest first (`GET /media/moderation/queue`),
 * with who uploaded it, how old their account is and the post it is on;
 * Approve makes it public, Reject deletes the file. Pending files are
 * private (`no-store`), so each one is fetched with the token into a blob
 * URL. The server enforces the role; this page only explains a 401/403.
 */
/* eslint-disable @next/next/no-img-element -- pending files need the token,
   so they are shown from blob URLs; next/image cannot fetch them. */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Check, ImageOff, Loader2, ShieldCheck, X } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { API_BASE, ApiError, fetchMediaBlob, getMediaQueue, reviewMedia, type ModerationMedia } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { accountAgeText, queueErrorText, reviewErrorText } from "@/lib/linkCard";
import { mediaSrc } from "@/lib/postMedia";

function PrivateImage({ url, alt }: { url: string | null; alt: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const file = mediaSrc(url, API_BASE);
    const token = getToken();
    if (!file || !token) {
      queueMicrotask(() => setFailed(true));
      return;
    }
    let alive = true;
    let made: string | null = null;
    fetchMediaBlob(file, token)
      .then((blob) => {
        if (!alive) return;
        made = URL.createObjectURL(blob);
        setSrc(made);
      })
      .catch(() => { if (alive) setFailed(true); });
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [url]);
  if (failed) {
    return (
      <div className="flex h-48 items-center justify-center gap-2 bg-slate-800 text-xs text-slate-400">
        <ImageOff className="w-4 h-4" aria-hidden="true" /> Could not load the image
      </div>
    );
  }
  if (!src) {
    return (
      <div className="flex h-48 items-center justify-center bg-slate-800">
        <Loader2 className="w-4 h-4 animate-spin text-slate-500" aria-hidden="true" />
      </div>
    );
  }
  return <img src={src} alt={alt} className="max-h-80 w-full object-contain bg-slate-950" />;
}

function QueueItem({
  item, now, onDone,
}: { item: ModerationMedia; now: number; onDone: (id: string, message: string) => void }) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: "approve" | "reject") {
    const token = getToken();
    if (!token || busy) return;
    setBusy(decision);
    setError(null);
    try {
      await reviewMedia(item.media_id, decision, token);
      onDone(item.media_id, decision === "approve" ? "Approved." : "Rejected; the file was deleted.");
    } catch (err) {
      setError(err instanceof ApiError ? reviewErrorText(err.status, err.body) : reviewErrorText(0, null));
      setBusy(null);
    }
  }

  const owner = item.owner;
  const who = owner?.handle ? `@${owner.handle}` : owner?.display_name || item.owner_did;
  return (
    <li data-media-review className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
      <PrivateImage url={item.url} alt={item.alt_text} />
      <div className="space-y-2 p-4 text-sm">
        <p className="text-slate-300">
          {item.kind === "LINK_THUMB" ? "Link card picture" : "Uploaded"} by{" "}
          <Link href={`/agents/${encodeURIComponent(item.owner_did)}`} className="text-cyan-400 hover:underline">
            {who}
          </Link>{" "}
          <span className="text-slate-500">({accountAgeText(owner?.created_at, now)})</span>
        </p>
        <p className="text-slate-400">
          <span className="text-slate-500">Alt text: </span>
          {item.alt_text || <em>none</em>}
        </p>
        {item.post ? (
          <p className="text-slate-400">
            <span className="text-slate-500">On post{item.post.hidden ? " (hidden)" : ""}: </span>
            <Link href={`/post/${encodeURIComponent(item.post.post_id)}`} className="text-cyan-400 hover:underline">
              {item.post.content || "(no text)"}
            </Link>
          </p>
        ) : (
          <p className="text-slate-500">Not on a post yet.</p>
        )}
        {error && <p role="alert" className="text-red-400">{error}</p>}
        <div className="flex gap-2 pt-1">
          <button
            type="button"
            onClick={() => decide("approve")}
            disabled={busy !== null}
            className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-white
                       hover:bg-emerald-500 disabled:opacity-50"
          >
            {busy === "approve" ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            Approve
          </button>
          <button
            type="button"
            onClick={() => decide("reject")}
            disabled={busy !== null}
            className="inline-flex items-center gap-1 rounded-lg bg-red-600 px-3 py-1.5 text-white
                       hover:bg-red-500 disabled:opacity-50"
          >
            {busy === "reject" ? <Loader2 className="w-4 h-4 animate-spin" /> : <X className="w-4 h-4" />}
            Reject
          </button>
        </div>
      </div>
    </li>
  );
}

export default function MediaReviewPage() {
  const [hydrated, setHydrated] = useState(false);
  const [token, setTokenState] = useState<string | null>(null);
  const [items, setItems] = useState<ModerationMedia[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState(0);

  useEffect(() => {
    queueMicrotask(() => {
      setTokenState(getToken());
      setHydrated(true);
    });
  }, []);

  const load = useCallback(async (t: string) => {
    setLoading(true);
    setError(null);
    try {
      const q = await getMediaQueue(t);
      setItems(q.media);
      setTotal(q.total);
      setLoadedAt(Date.now());
    } catch (err) {
      setError(queueErrorText(err instanceof ApiError ? err.status : 0));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (token) queueMicrotask(() => { void load(token); });
  }, [token, load]);

  function handleDone(id: string, message: string) {
    setItems((prev) => prev.filter((m) => m.media_id !== id));
    setTotal((n) => Math.max(0, n - 1));
    setNotice(message);
  }

  return (
    <AppShell>
      <div className="max-w-2xl mx-auto space-y-6">
        <header className="space-y-1">
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <ShieldCheck className="w-6 h-6 text-cyan-400" aria-hidden="true" /> Image review
          </h1>
          <p className="text-sm text-slate-500">
            Images from accounts under 7 days old, and from held posts, wait here. Only their
            author and moderators see them until you approve. Rejecting deletes the file.
          </p>
        </header>

        {!hydrated ? null : !token ? (
          <div className="space-y-3 text-center py-8">
            <p className="text-sm text-slate-400">Sign in with a FOUNDER or OPERATOR account to review images.</p>
            <Link
              href="/login?next=/moderation/media"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium"
            >
              Log in
            </Link>
          </div>
        ) : loading && items.length === 0 ? (
          <div className="flex justify-center py-12">
            <Loader2 className="animate-spin text-primary" size={24} />
          </div>
        ) : error ? (
          <p role="alert" className="text-sm text-red-400">{error}</p>
        ) : (
          <>
            <div className="flex items-center justify-between text-sm text-slate-400">
              <span>{total === 0 ? "Nothing waiting for review." : `${total} waiting`}</span>
              <button
                type="button"
                onClick={() => { setNotice(null); void load(token); }}
                className="text-cyan-400 hover:text-cyan-300"
              >
                Refresh
              </button>
            </div>
            {notice && <p role="status" className="text-sm text-emerald-400">{notice}</p>}
            <ul className="space-y-4">
              {items.map((m) => (
                <QueueItem key={m.media_id} item={m} now={loadedAt} onDone={handleDone} />
              ))}
            </ul>
          </>
        )}
      </div>
    </AppShell>
  );
}
