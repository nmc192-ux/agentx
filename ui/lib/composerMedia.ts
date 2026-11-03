/**
 * Layer 1 S4-10a2: attaching images in the composer.
 *
 * Pure helpers (no React, no fetch) so `node --test` can pin them. The
 * composer asks `GET /media/settings` whether uploads are on and shows the
 * attach button only then. Images are uploaded when the post is sent (so
 * the alt text the author typed last is the one stored), one at a time,
 * and the post names their ids in `media_ids`. An image already uploaded
 * with the same alt text is not sent again if the post itself fails.
 */

/** What `GET /media/settings` returns. */
export interface MediaSettings {
  media_enabled:      boolean;
  link_cards_enabled: boolean;
  max_images:         number;
  max_bytes:          number;
  max_alt_text:       number;
  mimes:              string[];
}

/** One image in the composer, before and after its upload. */
export interface Attachment {
  key:          string;
  file:         File | Blob;
  name:         string;
  previewUrl:   string;
  alt:          string;
  /** Set once uploaded; reused only while `uploadedAlt` still equals `alt`. */
  mediaId?:     string;
  uploadedAlt?: string;
  /** 0–100 while uploading, else undefined. */
  progress?:    number;
  error?:       string;
}

/** Shape check of an untrusted settings body; anything odd means "off". */
export function parseMediaSettings(body: unknown): MediaSettings | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  const num = (v: unknown) => typeof v === "number" && Number.isInteger(v) && v > 0;
  if (typeof b.media_enabled !== "boolean" || typeof b.link_cards_enabled !== "boolean") return null;
  if (!num(b.max_images) || !num(b.max_bytes) || !num(b.max_alt_text)) return null;
  if (!Array.isArray(b.mimes) || !b.mimes.every((m) => typeof m === "string" && m.startsWith("image/"))) {
    return null;
  }
  return {
    media_enabled:      b.media_enabled,
    link_cards_enabled: b.link_cards_enabled,
    max_images:         b.max_images as number,
    max_bytes:          b.max_bytes as number,
    max_alt_text:       b.max_alt_text as number,
    mimes:              b.mimes as string[],
  };
}

/** The attach button is shown only when uploads are on and there is room. */
export function canAttach(settings: MediaSettings | null, count: number): boolean {
  return !!settings && settings.media_enabled && count < settings.max_images;
}

/** Value for the file input's `accept` attribute. */
export function acceptAttr(settings: MediaSettings | null): string {
  return settings ? settings.mimes.join(",") : "";
}

function mb(bytes: number): string {
  return `${Math.round((bytes / (1024 * 1024)) * 10) / 10} MB`;
}

/**
 * Plain-word reason a picked file cannot be attached, or null when it may.
 * The server decides by the bytes, not the type the browser reports; this
 * only saves an upload that is sure to be refused.
 */
export function fileProblem(
  file: { name: string; type: string; size: number },
  settings: MediaSettings,
): string | null {
  if (!settings.mimes.includes(file.type)) {
    return `${file.name || "This file"} is not a JPEG, PNG, WebP or GIF image.`;
  }
  if (file.size <= 0) return `${file.name || "This file"} is empty.`;
  if (file.size > settings.max_bytes) {
    return `${file.name || "This file"} is larger than ${mb(settings.max_bytes)}.`;
  }
  return null;
}

/**
 * Split picked files into those to add and plain-word reasons for the rest,
 * keeping the total at `max_images`.
 */
export function pickFiles<F extends { name: string; type: string; size: number }>(
  files: F[],
  existing: number,
  settings: MediaSettings,
): { accepted: F[]; problems: string[] } {
  const accepted: F[] = [];
  const problems: string[] = [];
  let room = Math.max(0, settings.max_images - existing);
  let dropped = 0;
  for (const file of files) {
    const problem = fileProblem(file, settings);
    if (problem) {
      problems.push(problem);
    } else if (room > 0) {
      accepted.push(file);
      room -= 1;
    } else {
      dropped += 1;
    }
  }
  if (dropped > 0) {
    problems.push(`At most ${settings.max_images} images per post; ${dropped} not added.`);
  }
  return { accepted, problems };
}

/** True when this image still has to be (re)uploaded before posting. */
export function needsUpload(a: Attachment): boolean {
  return !a.mediaId || a.uploadedAlt !== a.alt.trim();
}

/** Alt text is optional but bounded; null when it is fine. */
export function altProblem(alt: string, settings: MediaSettings): string | null {
  return alt.trim().length > settings.max_alt_text
    ? `Image description is over ${settings.max_alt_text} characters.`
    : null;
}

/** May the post be sent? Text or at least one image, and no bad alt text. */
export function hasBody(content: string, attachments: Attachment[]): boolean {
  return content.trim().length > 0 || attachments.length > 0;
}

/** Plain words for a refused upload (`POST /media`) by status code. */
export function uploadErrorText(status: number): string {
  switch (status) {
    case 401: return "Please sign in again to upload images.";
    case 404: return "Images are switched off right now.";
    case 413: return "That image is too large (5 MB, or too many pixels or frames).";
    case 415: return "That file is not a JPEG, PNG, WebP or GIF image.";
    case 422: return "That image could not be read. Try another file.";
    case 429: return "Too many uploads. Wait a little and try again (50 a day).";
    case 507: return "The server is out of room for images. Try again later.";
    case 0:   return "The upload did not reach the server. Check your connection.";
    default:  return "The image could not be uploaded. Try again.";
  }
}

/** Upload function the composer passes in (lib/api `uploadMedia`). */
export type Uploader = (
  file: File | Blob,
  alt: string,
  onProgress: (percent: number) => void,
) => Promise<{ media_id: string }>;

/** Status-carrying error thrown by an uploader. */
export interface UploadFailure { status?: number }

/**
 * Upload every image that needs it, one at a time, reporting each change
 * through `update`. Returns the ids in the composer's order, or null when
 * an upload failed (the failed image carries the reason; the rest are
 * untouched so a retry sends only what is still missing).
 */
export async function uploadAll(
  attachments: Attachment[],
  upload: Uploader,
  update: (key: string, patch: Partial<Attachment>) => void,
): Promise<string[] | null> {
  const ids: string[] = [];
  for (const a of attachments) {
    if (!needsUpload(a)) {
      ids.push(a.mediaId as string);
      continue;
    }
    const alt = a.alt.trim();
    update(a.key, { progress: 0, error: undefined });
    try {
      const res = await upload(a.file, alt, (p) => update(a.key, { progress: p }));
      update(a.key, { mediaId: res.media_id, uploadedAlt: alt, progress: undefined });
      ids.push(res.media_id);
    } catch (err) {
      const status = (err as UploadFailure | null)?.status ?? -1;
      update(a.key, { progress: undefined, error: uploadErrorText(status) });
      return null;
    }
  }
  return ids;
}
