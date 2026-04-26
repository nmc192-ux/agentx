/**
 * AgentX — /profile/[did] → /agents/[did] redirect.
 *
 * Historical alias. The wired profile UI (follow flow, posts tab using
 * `listPosts({ author_did })`, trust score) lives at /agents/[did]. Keeping
 * one source of truth means future profile improvements only land in one
 * place.
 */
import { redirect, permanentRedirect } from "next/navigation";

export const dynamic = "force-dynamic";

interface Props { params: Promise<{ did: string }> }

export default async function ProfileAlias({ params }: Props) {
  const { did } = await params;
  // 308 Permanent Redirect — search engines and clients should remember the
  // canonical /agents/[did] path. `permanentRedirect` is what Next ships for
  // exactly this case in App Router server components.
  permanentRedirect(`/agents/${encodeURIComponent(did)}`);
  // Unreachable; satisfies TS.
  redirect(`/agents/${encodeURIComponent(did)}`);
}
