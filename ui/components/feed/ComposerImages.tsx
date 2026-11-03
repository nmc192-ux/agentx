"use client";

/**
 * AgentX — images in the composer (Layer 1 S4-10a2).
 *
 * `useComposerImages` holds the picked images; `ComposerImageButton` opens
 * the file picker and `ComposerImageList` shows each image with its
 * description (alt text) field, a remove button and upload progress. All of
 * it renders nothing unless `GET /media/settings` says uploads are on.
 * Uploads happen when the post is sent (`upload()`), so the description
 * typed last is the one stored.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ImagePlus, X } from "lucide-react";
import { getMediaSettings, uploadMedia } from "@/lib/api";
import {
  acceptAttr,
  altProblem,
  canAttach,
  pickFiles,
  uploadAll,
  type Attachment,
  type MediaSettings,
} from "@/lib/composerMedia";

export interface ComposerImages {
  settings:  MediaSettings | null;
  items:     Attachment[];
  problems:  string[];
  canAdd:    boolean;
  altError:  string | null;
  add:       (files: File[]) => void;
  remove:    (key: string) => void;
  setAlt:    (key: string, alt: string) => void;
  clear:     () => void;
  /** Uploads what is missing; the ids in order, or null on a failure. */
  upload:    (token: string) => Promise<string[] | null>;
}

let nextKey = 0;

export function useComposerImages(): ComposerImages {
  const [settings, setSettings] = useState<MediaSettings | null>(null);
  const [items, setItems] = useState<Attachment[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const itemsRef = useRef(items);
  itemsRef.current = items;

  useEffect(() => {
    let live = true;
    getMediaSettings().then((s) => { if (live) setSettings(s); });
    return () => { live = false; };
  }, []);

  // Revoke every preview URL when the composer goes away.
  useEffect(() => () => {
    for (const a of itemsRef.current) URL.revokeObjectURL(a.previewUrl);
  }, []);

  const update = useCallback((key: string, patch: Partial<Attachment>) => {
    setItems((prev) => prev.map((a) => (a.key === key ? { ...a, ...patch } : a)));
  }, []);

  const add = useCallback((files: File[]) => {
    if (!settings) return;
    const { accepted, problems: refused } = pickFiles(files, itemsRef.current.length, settings);
    setProblems(refused);
    if (accepted.length === 0) return;
    setItems((prev) => [
      ...prev,
      ...accepted.map((file) => ({
        key: `img-${++nextKey}`,
        file,
        name: file.name,
        previewUrl: URL.createObjectURL(file),
        alt: "",
      })),
    ]);
  }, [settings]);

  const remove = useCallback((key: string) => {
    setItems((prev) => {
      const gone = prev.find((a) => a.key === key);
      if (gone) URL.revokeObjectURL(gone.previewUrl);
      return prev.filter((a) => a.key !== key);
    });
    setProblems([]);
  }, []);

  const setAlt = useCallback((key: string, alt: string) => update(key, { alt }), [update]);

  const clear = useCallback(() => {
    for (const a of itemsRef.current) URL.revokeObjectURL(a.previewUrl);
    setItems([]);
    setProblems([]);
  }, []);

  const upload = useCallback(
    (token: string) =>
      uploadAll(
        itemsRef.current,
        (file, alt, onProgress) => uploadMedia(file, alt, token, onProgress),
        update,
      ),
    [update],
  );

  const altError = settings
    ? items.map((a) => altProblem(a.alt, settings)).find(Boolean) ?? null
    : null;

  return {
    settings,
    items,
    problems,
    canAdd: canAttach(settings, items.length),
    altError,
    add,
    remove,
    setAlt,
    clear,
    upload,
  };
}

export function ComposerImageButton({ images, disabled }: { images: ComposerImages; disabled?: boolean }) {
  const inputRef = useRef<HTMLInputElement>(null);
  if (!images.settings?.media_enabled) return null;
  return (
    <>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={disabled || !images.canAdd}
        title={images.canAdd ? "Add images" : `At most ${images.settings.max_images} images`}
        aria-label="Add images"
        className="p-1.5 rounded-full text-cyan-400 hover:bg-cyan-500/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        <ImagePlus className="w-4 h-4" />
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={acceptAttr(images.settings)}
        multiple
        hidden
        data-testid="composer-image-input"
        onChange={(e) => {
          images.add(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
    </>
  );
}

export function ComposerImageList({ images, disabled }: { images: ComposerImages; disabled?: boolean }) {
  const { items, problems, settings } = images;
  if (!settings?.media_enabled || (items.length === 0 && problems.length === 0)) return null;
  return (
    <div className="mt-3 space-y-2">
      {items.length > 0 && (
        <ul className="grid grid-cols-2 gap-2" aria-label="Images to post">
          {items.map((a, i) => (
            <li key={a.key} className="relative rounded-lg border border-slate-800 bg-slate-950 overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element -- local blob preview */}
              <img src={a.previewUrl} alt="" className="w-full h-28 object-cover" />
              <button
                type="button"
                onClick={() => images.remove(a.key)}
                disabled={disabled}
                aria-label={`Remove image ${i + 1}`}
                className="absolute top-1 right-1 p-1 rounded-full bg-black/70 text-slate-100 hover:bg-black disabled:opacity-40"
              >
                <X className="w-3.5 h-3.5" />
              </button>
              {a.progress !== undefined && (
                <div
                  className="h-1 bg-slate-800"
                  role="progressbar"
                  aria-label={`Uploading image ${i + 1}`}
                  aria-valuenow={a.progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div className="h-1 bg-cyan-500 transition-all" style={{ width: `${a.progress}%` }} />
                </div>
              )}
              <input
                type="text"
                value={a.alt}
                onChange={(e) => images.setAlt(a.key, e.target.value)}
                disabled={disabled}
                maxLength={settings.max_alt_text}
                placeholder="Describe the image (alt text)"
                aria-label={`Description of image ${i + 1}`}
                className="w-full bg-transparent px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 outline-none border-t border-slate-800"
              />
              {a.error && <p className="px-2 pb-1.5 text-[11px] text-red-400">{a.error}</p>}
            </li>
          ))}
        </ul>
      )}
      {problems.map((p) => (
        <p key={p} className="text-xs text-amber-400">{p}</p>
      ))}
      {images.altError && <p className="text-xs text-red-400">{images.altError}</p>}
    </div>
  );
}
