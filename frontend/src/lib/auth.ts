/**
 * AgentX — NextAuth Configuration
 * ════════════════════════════════
 * Uses a custom "credentials" provider that calls POST /auth/token
 * on the FastAPI backend, then stores the JWT in the NextAuth session.
 *
 * Session shape:
 *   session.user.agentDID    — the agent DID
 *   session.user.displayName — display name
 *   session.user.role        — governance role
 *   session.accessToken      — JWT for API calls
 */
import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import { loginWithDid, getAgent } from "./api";

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      name: "AgentX DID",
      credentials: {
        agentDid:    { label: "Agent DID",  type: "text"     },
        accessToken: { label: "JWT Token",  type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.agentDid || !credentials?.accessToken) return null;

        try {
          // Verify the JWT is valid by fetching the agent profile
          const agent = await getAgent(
            credentials.agentDid,
            credentials.accessToken,
          );
          if (!agent) return null;

          return {
            id:           agent.agent_did,
            agentDID:     agent.agent_did,
            displayName:  agent.display_name,
            role:         agent.governance_role,
            tier:         agent.tier,
            trustScore:   agent.trust_score,
            accessToken:  credentials.accessToken,
          };
        } catch {
          return null;
        }
      },
    }),
  ],

  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.agentDID    = (user as any).agentDID;
        token.displayName = (user as any).displayName;
        token.role        = (user as any).role;
        token.tier        = (user as any).tier;
        token.trustScore  = (user as any).trustScore;
        token.accessToken = (user as any).accessToken;
      }
      return token;
    },

    async session({ session, token }) {
      session.user = {
        ...session.user,
        agentDID:    token.agentDID    as string,
        displayName: token.displayName as string,
        role:        token.role        as string,
        tier:        token.tier        as string,
        trustScore:  token.trustScore  as number,
      } as any;
      (session as any).accessToken = token.accessToken as string;
      return session;
    },
  },

  pages: {
    signIn: "/login",
    error:  "/login",
  },

  session: {
    strategy: "jwt",
    maxAge:   60 * 60 * 8,   // 8-hour sessions
  },

  secret: process.env.NEXTAUTH_SECRET,
};

// Type augmentation so TypeScript knows our custom session shape
declare module "next-auth" {
  interface Session {
    accessToken: string;
    user: {
      agentDID:    string;
      displayName: string;
      role:        string;
      tier:        string;
      trustScore:  number;
      email?:      string;
      name?:       string;
      image?:      string;
    };
  }
}
