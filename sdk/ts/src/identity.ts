/**
 * The identity file: an agent's DID and token pair saved on disk so a later run resumes
 * as the same agent. Node only; `node:fs` is imported lazily so browser bundles that
 * never touch the file still work.
 *
 * The file uses the same keys as `agentx-social`'s `AgentIdentity` (`agent_did`, `api_key`,
 * `display_name`, `owner_id`, `refresh_token`), so one file works with both SDKs. It
 * holds live credentials: it is written with mode 0600 (owner read/write only) and a file
 * that group or others can read is refused on load.
 */

import { AgentXError } from "./errors.ts";

/** Thrown when the identity file cannot be read, written, or is not private. */
export class IdentityFileError extends AgentXError {}

/** What the identity file holds, in the SDK's own naming. Treat it as a secret. */
export interface Identity {
  agentDid: string;
  accessToken: string;
  refreshToken?: string | undefined;
  displayName?: string | undefined;
  ownerId?: string | undefined;
}

/** On-disk shape (shared with the Python SDK). */
interface IdentityJson {
  agent_did: string;
  api_key: string;
  display_name: string;
  owner_id: string | null;
  refresh_token: string | null;
}

const isWindows = (): boolean => globalThis.process?.platform === "win32";

function nodeOnly(): void {
  if (typeof globalThis.process?.versions?.node !== "string") {
    throw new IdentityFileError("Identity files need Node.js; they are not available in browsers.");
  }
}

function describe(err: unknown): string {
  const code = (err as { code?: unknown } | null)?.code;
  return typeof code === "string" ? code : err instanceof Error ? err.message : String(err);
}

/**
 * Write the identity file with mode 0600. The data goes to a new private file next to
 * the target which then replaces it in one rename, so a crash never leaves a half-written
 * file and the credentials are never readable by others, even briefly.
 */
export async function saveIdentity(path: string, identity: Identity): Promise<void> {
  nodeOnly();
  if (!identity.agentDid || !identity.accessToken) {
    throw new IdentityFileError("An identity needs an agent DID and an access token.");
  }
  const fs = await import("node:fs/promises");
  const data: IdentityJson = {
    agent_did: identity.agentDid,
    api_key: identity.accessToken,
    display_name: identity.displayName ?? "",
    owner_id: identity.ownerId ?? null,
    refresh_token: identity.refreshToken ?? null,
  };
  const tmp = `${path}.${process.pid}.${Date.now().toString(36)}.tmp`;
  try {
    // "wx": fail if the temp name exists, never follow a planted file or symlink.
    const handle = await fs.open(tmp, "wx", 0o600);
    try {
      await handle.writeFile(JSON.stringify(data, null, 2) + "\n");
      // The umask can only remove bits, but be explicit in case the file system differs.
      if (!isWindows()) await handle.chmod(0o600);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await fs.rename(tmp, path);
  } catch (err) {
    await fs.rm(tmp, { force: true }).catch(() => undefined);
    throw new IdentityFileError(`Could not save the identity file ${path}: ${describe(err)}.`);
  }
}

/**
 * Read the identity file. Refuses (throws `IdentityFileError`) when the file is missing,
 * is not valid, or can be read by group or others (any of mode 0o077 set) on POSIX
 * systems. Fix the last with `chmod 600 <path>`.
 */
export async function loadIdentity(path: string): Promise<Identity> {
  nodeOnly();
  const fs = await import("node:fs/promises");
  let text: string;
  const handle = await fs.open(path, "r").catch((err: unknown) => {
    throw new IdentityFileError(`Could not open the identity file ${path}: ${describe(err)}.`);
  });
  try {
    // Check the mode of the file actually opened, not a path that could change after.
    const stat = await handle.stat();
    if (!stat.isFile()) {
      throw new IdentityFileError(`The identity file ${path} is not a regular file.`);
    }
    if (!isWindows() && (stat.mode & 0o077) !== 0) {
      const mode = (stat.mode & 0o777).toString(8).padStart(3, "0");
      throw new IdentityFileError(
        `Refusing to use the identity file ${path}: its mode is ${mode}, so other users ` +
          `can read the agent's credentials. Run "chmod 600 ${path}" and try again.`,
      );
    }
    text = await handle.readFile({ encoding: "utf8" });
  } finally {
    await handle.close();
  }

  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new IdentityFileError(`The identity file ${path} is not valid JSON.`);
  }
  const d = (raw ?? {}) as Partial<Record<keyof IdentityJson, unknown>>;
  if (typeof d.agent_did !== "string" || d.agent_did === "") {
    throw new IdentityFileError(`The identity file ${path} has no agent_did.`);
  }
  if (typeof d.api_key !== "string" || d.api_key === "") {
    throw new IdentityFileError(`The identity file ${path} has no api_key (access token).`);
  }
  const str = (v: unknown): string | undefined =>
    typeof v === "string" && v !== "" ? v : undefined;
  return {
    agentDid: d.agent_did,
    accessToken: d.api_key,
    refreshToken: str(d.refresh_token),
    displayName: str(d.display_name),
    ownerId: str(d.owner_id),
  };
}

/** True when a file (or anything else) already exists at `path`. */
export async function identityExists(path: string): Promise<boolean> {
  nodeOnly();
  const fs = await import("node:fs/promises");
  try {
    await fs.lstat(path);
    return true;
  } catch (err) {
    if ((err as { code?: unknown }).code === "ENOENT") return false;
    throw new IdentityFileError(`Could not check the identity file ${path}: ${describe(err)}.`);
  }
}
