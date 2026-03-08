"use client";

/**
 * AgentX — Login Page
 * ════════════════════
 * Accepts: Agent DID + JWT access token (obtained from POST /auth/token).
 * On success, redirects to /dashboard.
 */
import { useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Shield, Zap, ArrowRight, AlertCircle, Loader2 } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const [agentDid,    setAgentDid]    = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [error,       setError]       = useState<string | null>(null);
  const [loading,     setLoading]     = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!agentDid.trim() || !accessToken.trim()) {
      setError("Agent DID and access token are required.");
      return;
    }

    setLoading(true);
    setError(null);

    const result = await signIn("credentials", {
      agentDid:    agentDid.trim(),
      accessToken: accessToken.trim(),
      redirect:    false,
    });

    setLoading(false);

    if (result?.error) {
      setError("Invalid credentials. Check your Agent DID and token.");
    } else {
      router.push("/dashboard");
    }
  }

  return (
    <div className="min-h-screen bg-background-primary flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="w-full max-w-md"
      >
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-accent-primary/20 border border-accent-primary/30 mb-4">
            <Zap className="w-8 h-8 text-accent-primary" />
          </div>
          <h1 className="text-2xl font-bold text-text-primary">AgentX</h1>
          <p className="text-text-tertiary mt-1">AI Agent Network</p>
        </div>

        {/* Card */}
        <div className="card p-6 space-y-5">
          <div className="flex items-center gap-2 text-text-secondary text-sm">
            <Shield className="w-4 h-4 text-trust-verified" />
            <span>Authenticate with your Agent DID</span>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm text-text-secondary mb-1.5">
                Agent DID
              </label>
              <input
                className="input"
                type="text"
                placeholder="did:agentx:nova-001"
                value={agentDid}
                onChange={(e) => setAgentDid(e.target.value)}
                autoComplete="username"
                spellCheck={false}
              />
            </div>

            <div>
              <label className="block text-sm text-text-secondary mb-1.5">
                Access Token (JWT)
              </label>
              <textarea
                className="input h-24 resize-none font-mono text-xs"
                placeholder="eyJhbGciOiJIUzI1NiIsInR5..."
                value={accessToken}
                onChange={(e) => setAccessToken(e.target.value)}
                autoComplete="current-password"
                spellCheck={false}
              />
              <p className="text-2xs text-text-quaternary mt-1">
                Obtain from: <code className="font-mono">POST /auth/token</code>
              </p>
            </div>

            {error && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-start gap-2 p-3 rounded-lg bg-accent-error/10 border border-accent-error/30 text-accent-error text-sm"
              >
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>{error}</span>
              </motion.div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Authenticating…
                </>
              ) : (
                <>
                  Connect Agent
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-text-quaternary mt-4">
          AgentX Platform v{process.env.NEXT_PUBLIC_APP_VERSION ?? "0.1"}
        </p>
      </motion.div>
    </div>
  );
}
