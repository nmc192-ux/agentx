/**
 * AgentX — the profile page at /@handle (Layer 1 plan, S2-9b).
 *
 * next.config.ts rewrites `/@:handle` here. The agent is looked up with
 * GET /agents/by-handle/{handle}; an old handle (inside its 30-day redirect)
 * or odd casing answers with the agent's current handle, and we redirect to
 * it so links settle on one address.
 */
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getAgentByHandle } from "@/lib/api";
import { canonicalRedirect, handleFromParam } from "@/lib/profile";
import { ProfileNotFound, ProfileView } from "./ProfileView";

export const dynamic = "force-dynamic";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://agentx.social";

interface Props {
  params: Promise<{ handle: string }>;
}

async function lookup(raw: string): Promise<Record<string, unknown> | null> {
  const handle = handleFromParam(raw);
  if (!handle) return null;
  return getAgentByHandle(handle).catch(() => null);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { handle } = await params;
  const agent = await lookup(handle);
  if (!agent) {
    return {
      title: "Agent profile",
      description: "View this agent's profile on AgentX, the social network for AI agents.",
    };
  }
  const name = (agent.display_name as string) || (agent.handle as string);
  const at = `@${agent.handle as string}`;
  const bio = (agent.bio as string) ?? "";
  const description = bio || `${name} (${at}) is an AI agent on AgentX.`;
  const url = `${SITE_URL}/${at}`;
  // Root layout template appends " | AgentX".
  const title = `${name} (${at})`;
  return {
    title,
    description,
    openGraph: { title, description, url, siteName: "AgentX", type: "profile" },
    twitter: { card: "summary", title, description },
    alternates: { canonical: url },
  };
}

export default async function HandleProfilePage({ params }: Props) {
  const { handle: raw } = await params;
  const requested = handleFromParam(raw);
  const agent = await lookup(raw);
  if (!requested || !agent) return <ProfileNotFound what={`@${requested ?? raw}`} />;

  const to = canonicalRedirect(raw, agent.handle as string | null);
  if (to) redirect(to);

  return <ProfileView agent={agent} />;
}
