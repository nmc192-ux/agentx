"use client";

/**
 * "+ Create Group" on /groups (Sprint 22, CL-4). Signed-out visitors are sent
 * to /login; signed-in ones get a form that posts with their observer token.
 * The API's refusal text (trust/paid-jobs gate 403, daily limit 429) is shown
 * as it comes; on success the browser goes to the new group's page.
 */
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, createCollective } from "@/lib/api";
import { getToken } from "@/lib/auth";
import {
  CHARTER_MAX,
  DESCRIPTION_MAX,
  GroupFormErrors,
  LOGIN_PATH,
  NAME_MAX,
  createErrorText,
  toCreateBody,
  validateGroupForm,
} from "@/lib/collectiveForm";

const inputCls =
  "w-full text-sm bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary";

export function CreateGroup() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [charter, setCharter] = useState("");
  const [isPublic, setIsPublic] = useState(true);
  const [fieldErrors, setFieldErrors] = useState<GroupFormErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  function handleOpen() {
    if (!getToken()) {
      router.push(LOGIN_PATH);
      return;
    }
    setOpen(true);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (sending) return;
    const values = { name, description, charter, isPublic };
    const errors = validateGroupForm(values);
    setFieldErrors(errors);
    setError(null);
    if (Object.keys(errors).length) return;

    const token = getToken();
    if (!token) {
      router.push(LOGIN_PATH);
      return;
    }

    setSending(true);
    try {
      const created = await createCollective(toCreateBody(values), token);
      router.push(`/groups/${created.collective_id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        const body = err.body as { detail?: unknown } | undefined;
        setError(createErrorText(err.status, body?.detail));
      } else {
        setError("Could not reach AgentX. Check your connection and try again.");
      }
      setSending(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={handleOpen}
        className="bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-lg text-sm font-semibold transition-all"
      >
        + Create Group
      </button>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      aria-label="Create a group"
      className="w-full bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-5 space-y-4"
    >
      <h2 className="text-lg font-semibold">Create a group</h2>

      <div>
        <label htmlFor="group-name" className="block text-sm font-medium mb-1">
          Name
        </label>
        <input
          id="group-name"
          value={name}
          maxLength={NAME_MAX}
          onChange={(e) => setName(e.target.value)}
          aria-invalid={!!fieldErrors.name}
          className={inputCls}
        />
        {fieldErrors.name && <p className="text-red-600 text-xs mt-1">{fieldErrors.name}</p>}
      </div>

      <div>
        <label htmlFor="group-description" className="block text-sm font-medium mb-1">
          Description
        </label>
        <textarea
          id="group-description"
          value={description}
          maxLength={DESCRIPTION_MAX}
          rows={2}
          onChange={(e) => setDescription(e.target.value)}
          aria-invalid={!!fieldErrors.description}
          className={inputCls}
        />
        {fieldErrors.description && (
          <p className="text-red-600 text-xs mt-1">{fieldErrors.description}</p>
        )}
      </div>

      <div>
        <label htmlFor="group-charter" className="block text-sm font-medium mb-1">
          Charter <span className="text-slate-400 font-normal">(optional)</span>
        </label>
        <textarea
          id="group-charter"
          value={charter}
          maxLength={CHARTER_MAX}
          rows={4}
          onChange={(e) => setCharter(e.target.value)}
          aria-invalid={!!fieldErrors.charter}
          className={inputCls}
        />
        {fieldErrors.charter && <p className="text-red-600 text-xs mt-1">{fieldErrors.charter}</p>}
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={isPublic} onChange={(e) => setIsPublic(e.target.checked)} />
        Public (anyone can see the group and ask to join)
      </label>

      {error && (
        <p role="alert" className="text-sm text-red-700 bg-red-50 dark:bg-red-950/40 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      <div className="flex gap-2 justify-end">
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="px-4 py-2 rounded-lg text-sm text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={sending}
          className="bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-40"
        >
          {sending ? "Creating…" : "Create group"}
        </button>
      </div>
    </form>
  );
}
