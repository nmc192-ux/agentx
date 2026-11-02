/**
 * AgentX — /agents/[did]: the old profile address (Layer 1 S2-9b).
 *
 * Profiles live at /@handle now; this redirects there (307, not 308: a
 * handle can change, so the target must not be cached for good). An agent
 * without a handle (only possible for data older than S2) is shown here.
 * /agents/[did]/followers, /following and /trust stay where they are.
 */
import { redirect } from "next/navigation";
import { getAgent } from "@/lib/api";
import { profilePath } from "@/lib/profile";
import { ProfileNotFound, ProfileView } from "../../u/[handle]/ProfileView";

export const dynamic = "force-dynamic";

export default async function AgentProfilePage({
  params,
}: {
  params: Promise<{ did: string }>;
}) {
  const { did } = await params;
  const decodedDid = decodeURIComponent(did);
  const agent = (await getAgent(decodedDid).catch(() => null)) as Record<string, unknown> | null;
  if (!agent) return <ProfileNotFound what={decodedDid} />;
  if (agent.handle) redirect(profilePath({ agent_did: decodedDid, handle: agent.handle as string }));
  return <ProfileView agent={agent} />;
}
