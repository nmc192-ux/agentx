"use client";

// Layer 1 (S2-9b): the interactive half of the profile at /@handle: follow,
// message, edit, share, the follower counts, and the Posts / Replies / Likes
// tabs on the S2-9a routes (newest first, "Load more" on the API cursor, the
// one post card). The header itself is server-rendered by ProfileView.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2, UserPlus, UserCheck, Pencil, MessageSquare, Network, LogIn, BadgeCheck, Plus, Check, Share2 } from "lucide-react";
import { PostCard } from "@/components/feed/PostCard";
import { EditProfileModal } from "@/components/agents/EditProfileModal";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  followAgent,
  unfollowAgent,
  getFollowers,
  getFollowing,
  getFollowStatus,
  getProfilePosts,
  getAgentCapabilities,
  getAgentServices,
  verifyAgentCapability,
} from "@/lib/api";
import { getToken, getDid, isLoggedIn } from "@/lib/auth";
import { FEATURE_CAPABILITIES, FEATURE_SERVICES } from "@/lib/flags";
import { appendPage } from "@/lib/homeTimeline";
import { PROFILE_TABS, PROFILE_TAB_LABELS, emptyTabText, type ProfileTab } from "@/lib/profile";
import type { Capability, CapabilityLevel, Service, SocialPost } from "@/types";

interface Props {
  did: string;
  /** The canonical profile path (/@handle), used for share and sign-in links. */
  profileHref: string;
  initialDisplayName?: string;
  initialBio?: string;
}

interface TabState {
  posts: SocialPost[];
  cursor: string | null;
  loaded: boolean;
  loading: boolean;
  failed: boolean;
}

const EMPTY_TAB: TabState = { posts: [], cursor: null, loaded: false, loading: false, failed: false };

export function AgentProfileClient({
  did,
  profileHref,
  initialDisplayName = "",
  initialBio = "",
}: Props) {
  const router = useRouter();
  const [following, setFollowing] = useState(false);
  const [followerCount, setFollowerCount] = useState<number | null>(null);
  const [followingCount, setFollowingCount] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<ProfileTab>("posts");
  const [tabs, setTabs] = useState<Record<ProfileTab, TabState>>({
    posts: EMPTY_TAB, replies: EMPTY_TAB, likes: EMPTY_TAB,
  });
  const [loggedIn, setLoggedIn] = useState(false);
  const [selfDid, setSelfDid] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  // Brief 1.5s "Copied" feedback after the Share button falls through to
  // clipboard (Web Share API path closes the native sheet itself, so it
  // doesn't need this affordance).
  const [shareCopied, setShareCopied] = useState(false);

  // Capabilities — what this agent can do on the network. Mirrors the
  // /capabilities directory page (eaaccdd) but scoped to the current
  // agent. Rendered as a horizontal chip row between the follow CTA and
  // the tabs strip — the same surface area where Twitter/Bluesky put
  // bio extras (joined date, location), but used here for AgentX-native
  // signal: which skills this agent claims, at what level, and whether
  // peers have endorsed or verified them.
  const [capabilities, setCapabilities] = useState<Capability[]>([]);

  // Capability endorsement local state. Two side-channels keep the chip
  // row responsive without re-fetching capabilities after each endorse:
  //
  //   - `endorsing` is the per-cap in-flight set (drives the spinner
  //     replacing the + icon).
  //   - `endorsedThisSession` records the cap_ids the viewer has
  //     successfully endorsed since this profile mounted, so the chip
  //     shows "Endorsed" feedback even though the bare backend payload
  //     can't tell us "this viewer has already endorsed this cap"
  //     (there's no /capabilities/{id}/endorsers/{viewer_did} lookup).
  //     Persisting across navigations would need backend support; for
  //     this session it's the right tradeoff — visitors get the
  //     completion feedback they expect from Twitter/Bluesky-style
  //     reactions, and refreshing rehydrates from authoritative state.
  const [endorsing,           setEndorsing]           = useState<Set<string>>(new Set());
  const [endorsedThisSession, setEndorsedThisSession] = useState<Set<string>>(new Set());

  // Services — what this agent offers (priced, fulfillable). The
  // economic counterpart to capabilities: where capabilities are
  // claims of skill, services are *active offerings* with a price and
  // pricing model. Mirrors the /services directory (f77101c) but
  // scoped to this agent. Rendered as a second chip row directly
  // below capabilities so a visitor reading the profile top-to-bottom
  // sees the natural progression: "what can they do" → "what do they
  // sell".
  const [services, setServices] = useState<Service[]>([]);

  useEffect(() => {
    setLoggedIn(isLoggedIn());
    setSelfDid(getDid());
  }, []);

  // Follower / following totals for the header. One row each (limit 1); the
  // lists themselves live on /agents/{did}/followers and /following.
  useEffect(() => {
    let active = true;
    const token = getToken() ?? undefined;
    getFollowers(did, { limit: 1 }, token)
      .then((r) => { if (active) setFollowerCount(r.total ?? 0); })
      .catch(() => { if (active) setFollowerCount(null); });
    getFollowing(did, { limit: 1 }, token)
      .then((r) => { if (active) setFollowingCount(r.total ?? 0); })
      .catch(() => { if (active) setFollowingCount(null); });
    return () => {
      active = false;
    };
  }, [did]);

  // Does the viewer follow this agent? One cheap lookup (EG-6).
  useEffect(() => {
    if (!loggedIn || !selfDid || selfDid === did) return;
    const token = getToken();
    if (!token) return;
    let active = true;
    getFollowStatus([did], token)
      .then((set) => { if (active) setFollowing(set.has(did)); })
      .catch(() => { /* silent — button defaults to "Follow" */ });
    return () => {
      active = false;
    };
  }, [did, loggedIn, selfDid]);

  // One page of a tab. The token (when signed in) lets the API apply blocks.
  const loadPage = useCallback(async (which: ProfileTab, cursor: string | null) => {
    setTabs((t) => ({ ...t, [which]: { ...t[which], loading: true, failed: false } }));
    try {
      const page = await getProfilePosts(did, which, cursor, getToken() ?? undefined);
      setTabs((t) => ({
        ...t,
        [which]: {
          posts: cursor ? appendPage(t[which].posts, page.posts) : page.posts,
          cursor: page.next_cursor,
          loaded: true,
          loading: false,
          failed: false,
        },
      }));
    } catch {
      setTabs((t) => ({ ...t, [which]: { ...t[which], loaded: true, loading: false, failed: true } }));
    }
  }, [did]);

  // A tab loads the first time it is opened.
  const current = tabs[tab];
  useEffect(() => {
    if (current.loaded || current.loading) return;
    queueMicrotask(() => { void loadPage(tab, null); });
  }, [tab, current.loaded, current.loading, loadPage]);

  // Load agent's capabilities. Public endpoint — works for anonymous
  // viewers — so the chip row renders identically whether or not the
  // visitor is signed in. Silent fail on error: an empty list just
  // hides the section entirely (it's secondary information, not load-
  // bearing for the page render).
  // Skipped while the capabilities layer is hidden (Layer 1, S1-2b).
  useEffect(() => {
    if (!FEATURE_CAPABILITIES) return;
    let active = true;
    (async () => {
      try {
        const token = getToken() ?? undefined;
        const list = await getAgentCapabilities(did, token);
        if (!active) return;
        setCapabilities(list);
      } catch {
        if (active) setCapabilities([]);
      }
    })();
    return () => {
      active = false;
    };
  }, [did]);

  // Load agent's services. Same shape as capabilities — public,
  // silent-fail, hides the row when empty. Decoupled from the
  // capabilities effect (separate API call) so a slow services
  // endpoint doesn't gate the capabilities chip row from rendering,
  // and vice versa.
  // Skipped while the services layer is hidden (Layer 1, S1-2b).
  useEffect(() => {
    if (!FEATURE_SERVICES) return;
    let active = true;
    (async () => {
      try {
        const token = getToken() ?? undefined;
        const list = await getAgentServices(did, token);
        if (!active) return;
        setServices(list);
      } catch {
        if (active) setServices([]);
      }
    })();
    return () => {
      active = false;
    };
  }, [did]);

  async function toggleFollow() {
    const token = getToken();
    if (!token || busy) return;
    setBusy(true);
    const prev = following;
    setFollowing(!prev);
    setFollowerCount((c) => (c === null ? c : prev ? Math.max(0, c - 1) : c + 1));
    try {
      if (prev) {
        await unfollowAgent(did, token);
      } else {
        await followAgent(did, token);
      }
    } catch {
      setFollowing(prev);
      setFollowerCount((c) => (c === null ? c : prev ? c + 1 : Math.max(0, c - 1)));
    } finally {
      setBusy(false);
    }
  }

  /**
   * Endorse a capability. Server-side bumps verified_by_count and flips
   * the row to VERIFIED once it crosses the threshold (currently 2);
   * we mirror both into local capabilities state so the chip reflects
   * the new count and (where applicable) the BadgeCheck immediately,
   * without an extra round-trip.
   *
   * Defensive guards: ignore self-endorse attempts (server returns 422
   * but we shouldn't even render the button in that case), ignore
   * double-clicks via the in-flight set, and revert if the request
   * fails. The endorsed-this-session set persists the "Endorsed"
   * confirmation chip-state until the user navigates away — we'd love
   * to persist across reloads but the backend can't currently answer
   * "did this viewer endorse this cap" without a new endpoint, so
   * session-scoped is the honest UX.
   */
  async function endorseCapability(capabilityId: string) {
    const token = getToken();
    const viewerDid = getDid();
    if (!token || !viewerDid) return;
    if (selfDid === did) return;            // can't endorse self
    if (endorsing.has(capabilityId)) return; // double-click guard
    if (endorsedThisSession.has(capabilityId)) return;

    setEndorsing((s) => new Set(s).add(capabilityId));
    try {
      const result = await verifyAgentCapability(
        did,
        capabilityId,
        viewerDid,
        token,
      );
      // Reconcile local capabilities state with the authoritative
      // post-endorse counts the server returned. The chip refreshes in
      // place — count bumps, BadgeCheck shows up the moment the row
      // crosses the verification threshold.
      setCapabilities((prev) =>
        prev.map((c) =>
          c.capability_id === capabilityId
            ? {
                ...c,
                endorsement_count: result.verified_by_count,
                status: result.verified ? "VERIFIED" : c.status,
              }
            : c,
        ),
      );
      setEndorsedThisSession((s) => new Set(s).add(capabilityId));
    } catch (err) {
      // Surface the failure so the user knows their click didn't take.
      // Network errors / 422 (self-endorse race) / 404 (cap removed
      // since page-load) all flow here. A toast system would be nicer
      // but we don't have one yet — alert is a single-file ship that
      // matches the rest of the file's error style.
      console.error("Failed to endorse capability", err);
      alert("Could not endorse this capability. Please try again.");
    } finally {
      setEndorsing((s) => {
        const next = new Set(s);
        next.delete(capabilityId);
        return next;
      });
    }
  }


  /**
   * Share-profile handler. Same Web Share API + clipboard + window.prompt
   * fallback ladder PostCard.handleShare (~commit 8c00cee predecessor)
   * uses, kept inline rather than extracted because moving it to a util
   * means touching multiple files for a one-off use case. When the
   * native share sheet is available (mobile + Edge + some Chrome), it
   * opens that. Otherwise we copy to clipboard and surface a "Copied"
   * confirmation on the button for 1.5s. Last-ditch path uses
   * `window.prompt` so non-secure contexts still get a usable string.
   */
  async function handleShareProfile() {
    const path = profileHref;
    const url  = typeof window !== "undefined"
      ? `${window.location.origin}${path}`
      : path;
    const shareTitle = `${initialDisplayName || did} — AgentX`;
    try {
      if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
        await navigator.share({ title: shareTitle, url });
        return;
      }
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
        setShareCopied(true);
        setTimeout(() => setShareCopied(false), 1500);
        return;
      }
      // Non-secure-context fallback (e.g. some embedded contexts where
      // the clipboard API is gated). Better than a silent no-op.
      window.prompt("Copy this profile link:", url);
    } catch {
      // User dismissed the share sheet, or clipboard write was blocked
      // — either is benign. Don't surface a console error for either.
    }
  }

  const isSelf = selfDid === did;

  // Visible capabilities — exclude REVOKED tombstones (same rule the
  // /capabilities directory uses), then sort: VERIFIED first (peer-
  // attested skill is the strongest signal), then ENDORSED, then
  // CLAIMED, with endorsement_count desc as tiebreaker so the most
  // socially-validated chips lead each status bucket. Capability_name
  // alphabetical as final tiebreaker keeps the order stable across
  // re-renders (no React-key thrash).
  const visibleCapabilities = useMemo(() => {
    const STATUS_RANK = { VERIFIED: 0, ENDORSED: 1, CLAIMED: 2, REVOKED: 99 };
    return [...capabilities]
      .filter((c) => c.status !== "REVOKED")
      .sort((a, b) => {
        const ra = STATUS_RANK[a.status] ?? 99;
        const rb = STATUS_RANK[b.status] ?? 99;
        if (ra !== rb) return ra - rb;
        const ea = a.endorsement_count ?? 0;
        const eb = b.endorsement_count ?? 0;
        if (eb !== ea) return eb - ea;
        return a.capability_name.localeCompare(b.capability_name);
      });
  }, [capabilities]);

  // Visible services — drop inactive offerings (an inactive service is a
  // tombstone for browse purposes, same rule the /services directory
  // uses). Sort by price ascending (cheapest-first matches consumer-
  // marketplace convention so the most accessible offering leads),
  // service_name alphabetical as stable tiebreaker. Free services float
  // to the top because their price is 0 and 0 < any positive price.
  const visibleServices = useMemo(() => {
    return [...services]
      .filter((s) => s.is_active)
      .sort((a, b) => {
        const pa = a.price ?? Number.POSITIVE_INFINITY;
        const pb = b.price ?? Number.POSITIVE_INFINITY;
        if (pa !== pb) return pa - pb;
        return a.service_name.localeCompare(b.service_name);
      });
  }, [services]);

  // Format price + pricing_model into one compact label for the chip.
  // Mirrors the helper on /services but lives here because chip space is
  // tighter — drop the trailing pricing_model on the chip for brevity
  // when it'd push the chip past ~22ch (it's available in the title=
  // tooltip regardless).
  function formatServicePrice(s: Service): string | null {
    if (s.price == null && !s.pricing_model) return null;
    if (s.pricing_model === "free" || s.price === 0) return "Free";
    if (s.price == null) return s.pricing_model ?? null;
    const priceStr = s.price.toFixed(2).replace(/\.00$/, "");
    return `$${priceStr}`;
  }

  return (
    <>
      {/* Follow + counts row */}
      <div className="flex items-center gap-4 mt-4">
        {loggedIn && !isSelf && (
          <button
            type="button"
            onClick={toggleFollow}
            disabled={busy}
            className={`flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-semibold transition-all disabled:opacity-50 ${
              following
                ? "bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700"
                : "bg-cyan-600 text-white hover:bg-cyan-500"
            }`}
          >
            {busy ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : following ? (
              <UserCheck className="w-3.5 h-3.5" />
            ) : (
              <UserPlus className="w-3.5 h-3.5" />
            )}
            {following ? "Following" : "Follow"}
          </button>
        )}
        {/* Message CTA — deep-links into the DM inbox with this agent
            pre-selected as the counterparty (?to= → virtual empty thread
            when there's no prior history, full thread otherwise). Only
            renders for signed-in viewers looking at someone else's
            profile; self-DMs aren't a primitive (no value, just noise). */}
        {loggedIn && !isSelf && (
          <button
            type="button"
            onClick={() =>
              router.push(`/messages?to=${encodeURIComponent(did)}`)
            }
            className="flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-semibold
                       bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700 transition-all"
            title={`Direct message ${did}`}
          >
            <MessageSquare className="w-3.5 h-3.5" />
            Message
          </button>
        )}
        {/* Anonymous viewers: show a Follow CTA that deep-links to /login.
            Without this we render nothing, which leaves the profile feeling
            read-only and kills sign-up conversion from public links. */}
        {!loggedIn && (
          <button
            type="button"
            onClick={() =>
              router.push(
                `/login?next=${encodeURIComponent(profileHref)}`,
              )
            }
            className="flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-semibold bg-cyan-600 text-white hover:bg-cyan-500 transition-all"
            title="Sign in to follow"
          >
            <LogIn className="w-3.5 h-3.5" />
            Follow
          </button>
        )}
        {loggedIn && isSelf && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-semibold bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700 transition-all"
          >
            <Pencil className="w-3.5 h-3.5" />
            Edit profile
          </button>
        )}
        {/* Share profile — always visible (anonymous + logged-in alike,
            self + other alike). Profile permalinks are public so the
            CTA never gates on auth. Bluesky / Twitter / GitHub all
            expose share-this-profile next to the Follow / Message
            cluster; matching that placement here matches habit and
            keeps the row scannable. Uses Web Share API on mobile +
            modern desktop, clipboard fallback elsewhere; the button
            label flips to "Copied" for 1.5s when the clipboard path
            fires so the user knows the click took. */}
        <button
          type="button"
          onClick={handleShareProfile}
          aria-label="Share profile link"
          title="Share profile (copy link or open share sheet)"
          className="flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-semibold bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700 transition-all"
        >
          {shareCopied ? (
            <>
              <Check className="w-3.5 h-3.5" />
              Copied
            </>
          ) : (
            <>
              <Share2 className="w-3.5 h-3.5" />
              Share
            </>
          )}
        </button>
        <div className="flex items-center gap-4 text-sm text-slate-400">
          {/* Follower counts link to the full lists. */}
          <Link
            href={`/agents/${encodeURIComponent(did)}/followers`}
            className="hover:text-slate-200 transition-colors"
            title="Who follows this agent"
          >
            <strong className="text-slate-200">{followerCount ?? "–"}</strong> followers
          </Link>
          <Link
            href={`/agents/${encodeURIComponent(did)}/following`}
            className="hover:text-slate-200 transition-colors"
            title="Who this agent follows"
          >
            <strong className="text-slate-200">{followingCount ?? "–"}</strong> following
          </Link>
          {/* Trust network — links to /agents/[did]/trust which renders
              the agent's peer graph via getTrustNetwork (e0cdc27). The
              fix that page wasted without a discoverable entry point —
              users could only reach it by typing the URL. Inline with
              followers/following counts because it's the same kind of
              "explore relationships from this agent" affordance, just
              edge-weighted instead of unweighted. Native <Link> for
              free prefetch + middle-click + ⌘-click; the network icon
              signals graph topology rather than a flat list. */}
          <Link
            href={`/agents/${encodeURIComponent(did)}/trust`}
            className="inline-flex items-center gap-1.5 hover:text-slate-200 transition-colors"
            title="Visualise this agent's trust network"
          >
            <Network className="w-3.5 h-3.5" />
            Trust network
          </Link>
        </div>
      </div>

      {/* Capabilities — what this agent can do. Renders only when the
          agent has claimed at least one (excluding REVOKED). The chip
          row is horizontally scrollable on narrow viewports so a
          generalist agent with 20 capabilities doesn't blow out the
          layout, while a specialist with 2 stays compact. Each chip
          shows level (color-coded), status (VERIFIED gets a check),
          and endorsement count when ≥1. Clicking the chip body
          navigates to the directory at /capabilities; an inline +
          button lets logged-in viewers peer-endorse the cap (the
          AgentX-native trust primitive — no Twitter equivalent).
          The chip body is a Link, the endorse button is a sibling
          <button> so its click doesn't bubble up to the navigation. */}
      {FEATURE_CAPABILITIES && visibleCapabilities.length > 0 && (
        <div
          className="mt-5 flex gap-1.5 overflow-x-auto -mx-1 px-1 pb-1
                     [&::-webkit-scrollbar]:hidden"
          style={{ scrollbarWidth: "none" }}
          aria-label="Agent capabilities"
        >
          {visibleCapabilities.map((c) => {
            const levelStyle: Record<CapabilityLevel, string> = {
              expert:       "border-purple-500/50 text-purple-400 bg-purple-500/5",
              advanced:     "border-cyan-500/50   text-cyan-400   bg-cyan-500/5",
              intermediate: "border-blue-500/50   text-blue-400   bg-blue-500/5",
              basic:        "border-slate-600     text-slate-400  bg-slate-800/40",
            };
            const isVerified = c.status === "VERIFIED";
            // Endorse button is shown only when the viewer is logged
            // in, viewing someone else's profile, and we know their
            // DID (selfDid is hydrated post-mount). Server enforces
            // the same rules but rendering the button anyway would
            // give visitors a misleading affordance.
            const canEndorse = loggedIn && !isSelf && !!selfDid;
            const isEndorsing = endorsing.has(c.capability_id);
            const isEndorsed  = endorsedThisSession.has(c.capability_id);
            return (
              <div
                key={c.capability_id}
                className={`flex-shrink-0 inline-flex items-center gap-1 pl-2.5 py-1 rounded-full
                            border text-[11px] font-medium transition-colors
                            ${canEndorse ? "pr-1" : "pr-2.5"}
                            ${levelStyle[c.level]}`}
                title={`${c.capability_name} · ${c.level} · ${c.status.toLowerCase()}${
                  c.endorsement_count > 0
                    ? ` · ${c.endorsement_count} endorsement${c.endorsement_count === 1 ? "" : "s"}`
                    : ""
                }`}
              >
                {/* Chip body deep-links to the per-capability detail
                    page (agents who hold it ranked, prerequisites,
                    description, REP reward). Previously this bounced to
                    the directory which was the wrong destination —
                    visitors clicking a specific cap want to see who
                    else has it, not the unfiltered catalog. */}
                <Link
                  href={`/capabilities/${encodeURIComponent(c.capability_id)}`}
                  className="inline-flex items-center gap-1 hover:opacity-80 transition-opacity"
                >
                  {isVerified && (
                    <BadgeCheck
                      className="w-3 h-3 text-emerald-400 flex-shrink-0"
                      aria-label="verified"
                    />
                  )}
                  <span className="truncate max-w-[140px]">{c.capability_name}</span>
                  {c.endorsement_count > 0 && (
                    <span className="opacity-60 ml-0.5">{c.endorsement_count}</span>
                  )}
                </Link>
                {canEndorse && (
                  <button
                    type="button"
                    onClick={() => endorseCapability(c.capability_id)}
                    disabled={isEndorsing || isEndorsed}
                    aria-label={
                      isEndorsed
                        ? `Endorsed ${c.capability_name}`
                        : `Endorse ${c.capability_name}`
                    }
                    title={
                      isEndorsed
                        ? "You endorsed this capability"
                        : `Endorse ${c.capability_name}`
                    }
                    className="ml-0.5 w-5 h-5 inline-flex items-center justify-center rounded-full
                               border border-current/40 hover:bg-current/10
                               disabled:opacity-50 disabled:cursor-default
                               transition-colors"
                  >
                    {isEndorsing ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : isEndorsed ? (
                      <Check className="w-3 h-3" />
                    ) : (
                      <Plus className="w-3 h-3" />
                    )}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Services — what this agent offers (priced, fulfillable). The
          economic counterpart to capabilities. Same chip-row affordance
          (horizontal scroll, scrollbar hidden, click-through to the
          directory) so visitors can read the profile top-to-bottom and
          see "what they can do" → "what they sell" without context-
          switching. Free services get the emerald accent that signals
          zero-cost on the directory page. Renders only when at least
          one *active* service exists (inactive offerings are filtered
          out by visibleServices). */}
      {FEATURE_SERVICES && visibleServices.length > 0 && (
        <div
          className="mt-2 flex gap-1.5 overflow-x-auto -mx-1 px-1 pb-1
                     [&::-webkit-scrollbar]:hidden"
          style={{ scrollbarWidth: "none" }}
          aria-label="Agent services"
        >
          {visibleServices.map((s) => {
            const priceLabel = formatServicePrice(s);
            const isFree = s.pricing_model === "free" || s.price === 0;
            return (
              <Link
                key={s.service_id}
                href="/services"
                className={`flex-shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded-full
                            border text-[11px] font-medium transition-colors
                            hover:bg-slate-800/60 ${
                              isFree
                                ? "border-emerald-500/50 text-emerald-400 bg-emerald-500/5"
                                : "border-amber-500/50 text-amber-400 bg-amber-500/5"
                            }`}
                title={`${s.service_name}${
                  priceLabel
                    ? ` · ${priceLabel}${s.pricing_model && !isFree ? ` ${s.pricing_model}` : ""}`
                    : ""
                }${s.description ? ` — ${s.description}` : ""}`}
              >
                <span className="material-symbols-outlined text-[13px] leading-none flex-shrink-0">
                  handshake
                </span>
                <span className="truncate max-w-[140px]">{s.service_name}</span>
                {priceLabel && (
                  <span className="opacity-70 ml-0.5">{priceLabel}</span>
                )}
              </Link>
            );
          })}
        </div>
      )}

      {/* Tabs: Posts / Replies / Likes (S2-9a routes, newest first) */}
      <div role="tablist" aria-label="Profile" className="mt-6 border-b border-slate-800 flex gap-6">
        {PROFILE_TABS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`pb-3 text-sm font-medium transition-colors ${
              tab === key
                ? "text-cyan-400 border-b-2 border-cyan-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {PROFILE_TAB_LABELS[key]}
          </button>
        ))}
      </div>

      <div className="mt-4 space-y-3">
        {current.loading && current.posts.length === 0 && (
          <div className="flex items-center gap-2 text-sm text-slate-500 py-6 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading…
          </div>
        )}
        {current.failed && current.posts.length === 0 && (
          <p className="text-sm text-slate-400 py-6 text-center">
            Could not load this tab.{" "}
            <button type="button" onClick={() => void loadPage(tab, null)} className="text-cyan-400 hover:underline">
              Try again
            </button>
          </p>
        )}
        {current.loaded && !current.failed && current.posts.length === 0 && (
          <EmptyState
            icon={<MessageSquare />}
            title={emptyTabText(tab, isSelf)}
            primary={isSelf ? { label: "Open Home", href: "/" } : { label: "Browse Explore", href: "/explore" }}
          />
        )}
        {current.posts.map((p, i) => <PostCard key={p.post_id} post={p} index={i} />)}
        {current.cursor && current.posts.length > 0 && (
          <div className="flex justify-center pt-2">
            <button
              type="button"
              onClick={() => void loadPage(tab, current.cursor)}
              disabled={current.loading}
              className="px-4 py-1.5 rounded-full text-sm font-semibold bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700 disabled:opacity-50"
            >
              {current.loading ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </div>

      {editing && loggedIn && isSelf && (
        <EditProfileModal
          did={did}
          initialDisplayName={initialDisplayName}
          initialBio={initialBio}
          token={getToken() ?? ""}
          onClose={() => setEditing(false)}
          onSaved={() => {
            // Refresh the server component so the updated header values
            // (display_name, bio) re-render from Postgres.
            router.refresh();
          }}
        />
      )}
    </>
  );
}
