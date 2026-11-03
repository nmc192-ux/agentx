"use client";

/**
 * AgentX — images on a post (Layer 1 S4-10a). A 1–4 image grid with alt
 * text, a lightbox, and "Image awaiting review" in place of an image the
 * reader may not see yet. What it shows is decided in lib/postMedia.ts.
 */
/* eslint-disable @next/next/no-img-element -- files come from the API's own
   /media/ paths with their own cache headers; next/image would proxy them. */
import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Clock, X } from "lucide-react";
import { API_BASE, fetchMediaBlob } from "@/lib/api";
import { getToken } from "@/lib/auth";
import {
  PENDING_TEXT, gridClass, mediaTiles, stepIndex, tileClass, type MediaTile,
} from "@/lib/postMedia";
import type { PostMedia } from "@/types";

type ImageTile = Extract<MediaTile, { kind: "image" }>;

/** The URL to put in `src`: the file itself, or (for a pending image the
 *  reader may see) a blob fetched with the token. Null while loading or
 *  when the fetch fails. */
function useTileSrc(tile: ImageTile): string | null {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!tile.authed) return;
    const token = getToken();
    if (!token) return;
    let alive = true;
    let made: string | null = null;
    fetchMediaBlob(tile.src, token)
      .then((blob) => {
        if (!alive) return;
        made = URL.createObjectURL(blob);
        setBlobUrl(made);
      })
      .catch(() => { /* shows the pending placeholder */ });
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [tile.authed, tile.src]);
  return tile.authed ? blobUrl : tile.src;
}

function PendingTile({ className }: { className: string }) {
  return (
    <div
      data-media-pending
      className={`flex flex-col items-center justify-center gap-1 bg-slate-800/80
                  text-slate-400 text-xs ${className}`}
    >
      <Clock className="w-4 h-4" aria-hidden="true" />
      {PENDING_TEXT}
    </div>
  );
}

function ImageTileView({
  tile, className, onOpen,
}: { tile: ImageTile; className: string; onOpen: () => void }) {
  const src = useTileSrc(tile);
  if (!src) return <PendingTile className={className} />;
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onOpen(); }}
      className={`relative block overflow-hidden bg-slate-800 focus-visible:outline-none
                  focus-visible:ring-2 focus-visible:ring-cyan-500/60 ${className}`}
      aria-label={tile.alt ? `Open image: ${tile.alt}` : "Open image"}
    >
      <img
        src={src}
        alt={tile.alt}
        width={tile.width || undefined}
        height={tile.height || undefined}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        className="w-full h-full object-cover"
      />
      {tile.authed && (
        <span className="absolute left-1 top-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-amber-300">
          Awaiting review: only you and moderators see it
        </span>
      )}
      {tile.alt && (
        <span className="absolute right-1 bottom-1 rounded bg-black/70 px-1 text-[10px] font-semibold text-slate-200">
          ALT
        </span>
      )}
    </button>
  );
}

function Lightbox({
  tiles, start, onClose,
}: { tiles: ImageTile[]; start: number; onClose: () => void }) {
  const [i, setI] = useState(start);
  const n = tiles.length;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") setI((x) => stepIndex(x, 1, n));
      if (e.key === "ArrowLeft") setI((x) => stepIndex(x, -1, n));
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [n, onClose]);
  const tile = tiles[i];
  return (
    // Escape closes it (keydown listener above); a click on the dark area
    // around the image closes it too, and no click leaks to the post card.
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Image viewer"
      className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/90 p-4"
      onClick={(e) => { e.stopPropagation(); if (e.target === e.currentTarget) onClose(); }}
    >
      <button
        type="button"
        onClick={onClose}
        className="absolute right-4 top-4 rounded-full p-2 text-slate-200 hover:bg-white/10"
        aria-label="Close image viewer"
      >
        <X className="w-5 h-5" />
      </button>
      {n > 1 && (
        <>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setI((x) => stepIndex(x, -1, n)); }}
            className="absolute left-4 top-1/2 -translate-y-1/2 rounded-full p-2 text-slate-200 hover:bg-white/10"
            aria-label="Previous image"
          >
            <ChevronLeft className="w-6 h-6" />
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setI((x) => stepIndex(x, 1, n)); }}
            className="absolute right-4 top-1/2 -translate-y-1/2 rounded-full p-2 text-slate-200 hover:bg-white/10"
            aria-label="Next image"
          >
            <ChevronRight className="w-6 h-6" />
          </button>
        </>
      )}
      <div className="flex max-h-full flex-col items-center">
        <LightboxImage key={tile.id} tile={tile} />
        {tile.alt && (
          <p className="mt-3 max-w-2xl text-center text-sm text-slate-300 whitespace-pre-wrap">{tile.alt}</p>
        )}
        {n > 1 && <p className="mt-1 text-xs text-slate-500">{i + 1} of {n}</p>}
      </div>
    </div>
  );
}

function LightboxImage({ tile }: { tile: ImageTile }) {
  const src = useTileSrc(tile);
  if (!src) return <PendingTile className="h-64 w-64 rounded-lg" />;
  return (
    <img
      src={src}
      alt={tile.alt}
      referrerPolicy="no-referrer"
      className="max-h-[80vh] max-w-[90vw] object-contain"
    />
  );
}

export function PostMediaGrid({ media }: { media?: PostMedia[] | null }) {
  const [open, setOpen] = useState<number | null>(null);
  const tiles = mediaTiles(media, API_BASE);
  if (tiles.length === 0) return null;
  const images = tiles.filter((t): t is ImageTile => t.kind === "image");
  const n = tiles.length;
  return (
    <div
      data-post-media
      className={`${gridClass(n)} gap-0.5 mt-2 mb-2 overflow-hidden rounded-xl border border-slate-800`}
    >
      {tiles.map((t, i) =>
        t.kind === "pending" ? (
          <PendingTile key={t.id} className={`${tileClass(i, n)} min-h-32`} />
        ) : (
          <ImageTileView
            key={t.id}
            tile={t}
            className={tileClass(i, n)}
            onOpen={() => setOpen(images.indexOf(t))}
          />
        ),
      )}
      {open !== null && images.length > 0 && (
        <Lightbox tiles={images} start={open} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}
