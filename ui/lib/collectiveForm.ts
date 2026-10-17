/**
 * "Create Group" form logic (Sprint 22, CL-4), kept free of React and imports
 * so `node --test` can run it directly.
 *
 * Limits mirror the API's `CollectiveCreate` model
 * (platform/src/models/collective.py).
 */

export const NAME_MAX = 128;
export const DESCRIPTION_MAX = 1024;
export const CHARTER_MAX = 5000;

export interface GroupFormValues {
  name: string;
  description: string;
  charter: string;
  isPublic: boolean;
}

export interface CreateCollectiveBody {
  name: string;
  description: string;
  charter: string | null;
  is_public: boolean;
}

export type GroupFormErrors = Partial<Record<"name" | "description" | "charter", string>>;

/** Field errors for the form; an empty object means it can be sent. */
export function validateGroupForm(v: GroupFormValues): GroupFormErrors {
  const errors: GroupFormErrors = {};
  const name = v.name.trim();
  const description = v.description.trim();
  const charter = v.charter.trim();

  if (!name) errors.name = "Give the group a name.";
  else if (name.length > NAME_MAX) errors.name = `Name is at most ${NAME_MAX} characters.`;

  if (!description) errors.description = "Say in a sentence what the group is for.";
  else if (description.length > DESCRIPTION_MAX)
    errors.description = `Description is at most ${DESCRIPTION_MAX} characters.`;

  if (charter.length > CHARTER_MAX) errors.charter = `Charter is at most ${CHARTER_MAX} characters.`;

  return errors;
}

/** The JSON body for POST /collectives. A blank charter is sent as null. */
export function toCreateBody(v: GroupFormValues): CreateCollectiveBody {
  const charter = v.charter.trim();
  return {
    name: v.name.trim(),
    description: v.description.trim(),
    charter: charter ? charter : null,
    is_public: v.isPublic,
  };
}

/**
 * Text to show when the API refuses. The gate's 403 ("how to qualify") and
 * the daily limit's 429 are plain strings and are shown as they are; a 422
 * lists its problems; anything else gets a short fallback.
 */
export function createErrorText(status: number, detail: unknown): string {
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  if (status === 401) return "Your sign-in has expired. Sign in again to create a group.";
  return `Could not create the group (error ${status}). Try again in a moment.`;
}

/** Where a signed-out visitor is sent: the login page, coming back to /groups. */
export const LOGIN_PATH = "/login?next=%2Fgroups";
