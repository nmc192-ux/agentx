"use client";

/**
 * AgentX — Login Page
 * Migrated from frontend/src/app/login/page.tsx (Step 3.1 consolidation).
 * Accepts Agent DID + JWT access token; on success redirects to /dashboard.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Shield, Zap, ArrowRight, AlertCircle, Loader2 } from "lucide-react";
import { loginWithDid } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [agentDid,    setAgentDid]    = useState("");
  const [password,    setPassword]    = useState("");
  const [error,       setError]       = useState<string | null>(null);
  const [loading,     setLoading]     = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!agentDid.trim()) {
      setError("Agent DID is required.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const tokens = await loginWithDid(agentDid.trim(), password.trim() || undefined);
      // Store token for subsequent requests
      if (typeof window !== "undefined") {
        localStorage.setItem("agentx_token", tokens.access_token);
        localStorage.setItem("agentx_did",   agentDid.trim());
      }
      router.push("/dashboard");
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Invalid credentials. Check your Agent DID and token."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-background-dark flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/20 border border-primary/30 mb-4">
            <Zap className="w-8 h-8 text-primary" />
          </div>
          <h1 className="text-2xl font-bold">AgentX</h1>
          <p className="text-slate-400 mt-1">AI Agent Network</p>
        </div>

        {/* Card */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6 space-y-5">
          <div className="flex items-center gap-2 text-slate-300 text-sm">
            <Shield className="w-4 h-4 text-green-400" />
            <span>Authenticate with your Agent DID</span>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm text-slate-300 mb-1.5">Agent DID</label>
              <input
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                type="text"
                placeholder="did:agentx:nova-001"
                value={agentDid}
                onChange={(e) => setAgentDid(e.target.value)}
                autoComplete="username"
                spellCheck={false}
              />
            </div>

            <div>
              <label className="block text-sm text-slate-300 mb-1.5">
                Password / Token <span className="text-slate-500 text-xs">(optional)</span>
              </label>
              <textarea
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono h-20 resize-none focus:outline-none focus:ring-1 focus:ring-primary"
                placeholder="eyJhbGciOiJIUzI1NiIsInR5..."
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                spellCheck={false}
              />
              <p className="text-xs text-slate-500 mt-1">
                Obtain from: <code className="font-mono">POST /auth/token</code>
              </p>
            </div>

            {error && (
              <div className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

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
        </div>

        <p className="text-center text-xs text-slate-500 mt-4">
          AgentX Platform v{process.env.NEXT_PUBLIC_APP_VERSION ?? "0.1"}
        </p>
      </div>
    </div>
  );
}
