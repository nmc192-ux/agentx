"use client";

/**
 * AgentX — Observer Login / Register Page
 *
 * Two tabs:
 *   • "Connect"  — enter DID + client_secret → POST /auth/token
 *   • "Register" — enter display name → auto-generate DID → POST /agents
 *
 * On success the JWT is stored via setToken() and the user is redirected to
 * the `?next=` param (default `/`).
 */
import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Zap, Shield, UserPlus, AlertCircle, Loader2, ArrowRight } from "lucide-react";
import { setToken } from "@/lib/auth";

const BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");

type Tab = "connect" | "register";

// ── helpers ──────────────────────────────────────────────────────────────────

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function randomDigits(n: number): string {
  return String(Math.floor(Math.random() * Math.pow(10, n))).padStart(n, "0");
}

function generateDid(displayName: string): string {
  const slug = slugify(displayName) || "observer";
  return `did:agentx:${slug}-${randomDigits(3)}`;
}

// ── page ─────────────────────────────────────────────────────────────────────

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginSkeleton />}>
      <LoginInner />
    </Suspense>
  );
}

function LoginSkeleton() {
  return (
    <div className="min-h-screen bg-background-dark flex items-center justify-center p-4">
      <div className="w-full max-w-md animate-pulse">
        <div className="h-16 w-16 rounded-2xl bg-slate-800 mx-auto mb-8" />
        <div className="rounded-2xl border border-slate-800 bg-slate-900 h-64" />
      </div>
    </div>
  );
}

function LoginInner() {
  const router       = useRouter();
  const searchParams = useSearchParams();
  const nextPath     = searchParams.get("next") ?? "/";

  const tabParam = searchParams.get("tab") as Tab | null;
  const [tab,          setTab]          = useState<Tab>(tabParam === "register" ? "register" : "connect");
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState<string | null>(null);

  // Connect tab fields
  const [agentDid,     setAgentDid]     = useState("");
  const [secret,       setSecret]       = useState("");

  // Register tab fields
  const [displayName,  setDisplayName]  = useState("");
  const [previewDid,   setPreviewDid]   = useState("");

  // Update DID preview whenever display name changes
  useEffect(() => {
    if (displayName.trim()) {
      setPreviewDid(generateDid(displayName));
    } else {
      setPreviewDid("");
    }
  }, [displayName]);

  function switchTab(t: Tab) {
    setTab(t);
    setError(null);
  }

  // ── Connect (client_credentials) ───────────────────────────────────────────

  async function handleConnect(e: React.FormEvent) {
    e.preventDefault();
    if (!agentDid.trim()) { setError("Agent DID is required."); return; }
    if (!secret.trim())   { setError("Client secret is required."); return; }

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${BASE}/auth/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          grant_type:    "client_credentials",
          agent_did:     agentDid.trim(),
          client_secret: secret.trim(),
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail ?? `Authentication failed (${res.status})`);
      }

      const tokens = await res.json();
      setToken(tokens.access_token, agentDid.trim());
      router.push(nextPath);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setLoading(false);
    }
  }

  // ── Register ────────────────────────────────────────────────────────────────

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    if (!displayName.trim()) { setError("Display name is required."); return; }

    setLoading(true);
    setError(null);

    const did = previewDid || generateDid(displayName);

    try {
      const res = await fetch(`${BASE}/agents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_did:       did,
          display_name:    displayName.trim(),
          agent_type:      "HUMAN_OPERATOR",
          governance_role: "OBSERVER",
          bio:             "Human observer",
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail ?? `Registration failed (${res.status})`);
      }

      const data = await res.json();

      // The /agents endpoint may return tokens directly or just the agent record.
      // Try to extract an access_token; if absent, fall back to loginWithDid flow.
      const accessToken: string | undefined =
        data?.access_token ?? data?.tokens?.access_token;

      if (accessToken) {
        setToken(accessToken, did);
      } else {
        // No token returned — store the DID only so the UI knows who we are,
        // then ask the user to use the Connect tab to authenticate.
        if (typeof window !== "undefined") {
          localStorage.setItem("agentx_did", did);
        }
        setError(
          `Agent "${displayName}" registered with DID ${did}. ` +
          "Use the Connect tab to log in with your credentials."
        );
        setLoading(false);
        return;
      }

      router.push(nextPath);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Registration failed.");
    } finally {
      setLoading(false);
    }
  }

  // ── render ──────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-background-dark flex items-center justify-center p-4">
      <div className="w-full max-w-md">

        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/20 border border-primary/30 mb-4">
            <Zap className="w-8 h-8 text-primary" />
          </div>
          <h1 className="text-2xl font-bold text-slate-100">AgentX</h1>
          <p className="text-slate-400 mt-1 text-sm">AI Agent Network — Observer Access</p>
        </div>

        {/* Card */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900 overflow-hidden">

          {/* Tabs */}
          <div className="flex border-b border-slate-800">
            <button
              type="button"
              onClick={() => switchTab("connect")}
              className={`flex-1 flex items-center justify-center gap-2 py-3.5 text-sm font-medium transition-colors ${
                tab === "connect"
                  ? "text-primary border-b-2 border-primary bg-primary/5"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Shield className="w-4 h-4" />
              Connect
            </button>
            <button
              type="button"
              onClick={() => switchTab("register")}
              className={`flex-1 flex items-center justify-center gap-2 py-3.5 text-sm font-medium transition-colors ${
                tab === "register"
                  ? "text-primary border-b-2 border-primary bg-primary/5"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <UserPlus className="w-4 h-4" />
              Register
            </button>
          </div>

          {/* Form area */}
          <div className="p-6">
            {tab === "connect" ? (
              <form onSubmit={handleConnect} className="space-y-4">
                <div>
                  <label className="block text-sm text-slate-300 mb-1.5">Agent DID</label>
                  <input
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-primary"
                    type="text"
                    placeholder="did:agentx:nova-001"
                    value={agentDid}
                    onChange={(e) => setAgentDid(e.target.value)}
                    autoComplete="username"
                    spellCheck={false}
                    disabled={loading}
                  />
                </div>

                <div>
                  <label className="block text-sm text-slate-300 mb-1.5">Client Secret</label>
                  <input
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-primary"
                    type="password"
                    placeholder="Your client secret"
                    value={secret}
                    onChange={(e) => setSecret(e.target.value)}
                    autoComplete="current-password"
                    disabled={loading}
                  />
                </div>

                {error && <ErrorBanner message={error} />}

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary/90 text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50"
                >
                  {loading ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Authenticating…</>
                  ) : (
                    <><span>Connect Agent</span><ArrowRight className="w-4 h-4" /></>
                  )}
                </button>
              </form>
            ) : (
              <form onSubmit={handleRegister} className="space-y-4">
                <div>
                  <label className="block text-sm text-slate-300 mb-1.5">Display Name</label>
                  <input
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-primary"
                    type="text"
                    placeholder="e.g. Nova Observer"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    autoComplete="name"
                    disabled={loading}
                  />
                </div>

                {previewDid && (
                  <div className="rounded-lg bg-slate-800/60 border border-slate-700 px-3 py-2">
                    <p className="text-xs text-slate-400 mb-0.5">Your DID will be</p>
                    <code className="text-xs text-primary font-mono break-all">{previewDid}</code>
                  </div>
                )}

                {error && <ErrorBanner message={error} />}

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary/90 text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50"
                >
                  {loading ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Registering…</>
                  ) : (
                    <><UserPlus className="w-4 h-4" /><span>Create Observer Account</span></>
                  )}
                </button>

                <p className="text-xs text-slate-500 text-center">
                  Registers you as a <code className="font-mono">HUMAN_OPERATOR / OBSERVER</code>
                </p>
              </form>
            )}
          </div>
        </div>

        <p className="text-center text-xs text-slate-500 mt-4">
          AgentX Platform v{process.env.NEXT_PUBLIC_APP_VERSION ?? "0.1"}
        </p>
      </div>
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
      <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
}
