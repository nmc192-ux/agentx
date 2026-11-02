// Layer 1 (S2-10b): how notifications and direct messages name a person.
// The server sends the handle (S2-10a); these plain functions decide what to
// show, so `people.test.ts` can pin the rules without a browser. A handle
// shows as "@handle"; with none we fall back to the name, then the short DID.

interface Named {
  did?: string | null;
  name?: string | null;
  handle?: string | null;
}

/** "@nova_002" for a handle, or null when there is none. */
export function atHandle(handle: string | null | undefined): string | null {
  const h = (handle ?? "").trim().replace(/^@+/, "");
  return h ? `@${h}` : null;
}

/** The last part of a DID ("did:agentx:lyra-003" → "lyra-003"). */
export function didSlug(did: string): string {
  return did.split(":").pop() || did;
}

/** The one-line name for a person: @handle, else name, else short DID, else `fallback`. */
export function personLabel(p: Named, fallback = "Someone"): string {
  return (
    atHandle(p.handle) ??
    (p.name?.trim() || null) ??
    (p.did ? didSlug(p.did) : null) ??
    fallback
  );
}

/** Where a click on the person goes: their /@handle page, else the DID page. */
export function personHref(p: Named): string | null {
  const h = atHandle(p.handle);
  if (h) return `/${h}`;
  return p.did ? `/agents/${encodeURIComponent(p.did)}` : null;
}

interface NotifFrom {
  from_did: string | null;
  from_name: string | null;
  from_handle?: string | null;
}

export function notifPerson(n: NotifFrom): Named {
  return { did: n.from_did, name: n.from_name, handle: n.from_handle };
}

interface MessageSides {
  sender_agent_did: string;
  receiver_agent_did: string;
  sender_handle?: string | null;
  receiver_handle?: string | null;
}

/** The handle of the other party in a message, given my DID. */
export function counterpartyHandle(m: MessageSides, myDid: string): string | null {
  const h = m.sender_agent_did === myDid ? m.receiver_handle : m.sender_handle;
  return atHandle(h) ? (h as string) : null;
}
