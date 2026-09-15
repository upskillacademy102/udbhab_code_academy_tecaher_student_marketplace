import { useEffect, useMemo, useRef, useState } from "react";

/**
 * Drag-to-adjust photo cropper, shown between "pick a file" and "upload it."
 *
 * Produces a real square crop (drag to pan, +/- or scroll to zoom) rather
 * than uploading whatever rectangle the OS file picker happened to hand
 * back — the avatar is shown circular everywhere in the app, so a badly
 * framed upload (a face pushed to one corner) stayed wrong forever with no
 * way to fix it short of re-uploading a manually pre-cropped file.
 *
 * The circle is a visual mask only; the exported file is the square behind
 * it, matching how every avatar in the app is rendered (a square photo,
 * rounded by CSS) rather than baking transparency into the upload.
 */

const BOX = 280; // px, fixed so the crop math doesn't depend on layout
const MIN_ZOOM = 1;
const MAX_ZOOM = 3;
const OUTPUT = 512; // exported square size, px

interface Props {
  file: File;
  onCancel: () => void;
  onConfirm: (blob: Blob) => void;
  /** True while the parent is uploading the confirmed crop — keeps the modal's button busy past the (near-instant) canvas export. */
  uploading?: boolean;
}

export function PhotoCropModal({ file, onCancel, onConfirm, uploading = false }: Props) {
  const objectUrl = useMemo(() => URL.createObjectURL(file), [file]);
  useEffect(() => () => URL.revokeObjectURL(objectUrl), [objectUrl]);

  const imgRef = useRef<HTMLImageElement>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [busy, setBusy] = useState(false);
  const drag = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);

  // baseScale: the zoom=1 scale that makes the image fully cover the box
  // (like CSS background-size: cover) so there's never a gap around it.
  const baseScale = natural ? Math.max(BOX / natural.w, BOX / natural.h) : 1;
  const scale = baseScale * zoom;
  const dispW = natural ? natural.w * scale : BOX;
  const dispH = natural ? natural.h * scale : BOX;
  const maxPanX = Math.max(0, (dispW - BOX) / 2);
  const maxPanY = Math.max(0, (dispH - BOX) / 2);

  function clamp(v: number, max: number) {
    return Math.min(max, Math.max(-max, v));
  }

  // Re-clamp whenever zoom shrinks the allowed pan range.
  useEffect(() => {
    setPan((p) => ({ x: clamp(p.x, maxPanX), y: clamp(p.y, maxPanY) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxPanX, maxPanY]);

  function onPointerDown(e: React.PointerEvent) {
    (e.target as Element).setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
  }
  function onPointerMove(e: React.PointerEvent) {
    if (!drag.current) return;
    const dx = e.clientX - drag.current.x;
    const dy = e.clientY - drag.current.y;
    setPan({ x: clamp(drag.current.panX + dx, maxPanX), y: clamp(drag.current.panY + dy, maxPanY) });
  }
  function onPointerUp() {
    drag.current = null;
  }
  function onWheel(e: React.WheelEvent) {
    e.preventDefault();
    setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z - e.deltaY * 0.0015)));
  }

  async function confirm() {
    const img = imgRef.current;
    if (!img || !natural || busy) return;
    setBusy(true);
    try {
      // The image's top-left corner in box-local coordinates.
      const imgLeft = BOX / 2 - dispW / 2 + pan.x;
      const imgTop = BOX / 2 - dispH / 2 + pan.y;
      const inv = 1 / scale;
      const sx = -imgLeft * inv;
      const sy = -imgTop * inv;
      const sSize = BOX * inv;

      const canvas = document.createElement("canvas");
      canvas.width = OUTPUT;
      canvas.height = OUTPUT;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Canvas not supported");
      ctx.drawImage(img, sx, sy, sSize, sSize, 0, 0, OUTPUT, OUTPUT);

      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
      if (!blob) throw new Error("Could not export the cropped photo.");
      onConfirm(blob);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex flex-col items-center justify-center bg-ink-900/95 p-4">
      <div className="flex w-full max-w-sm items-center justify-between pb-3">
        <button
          type="button"
          onClick={onCancel}
          className="grid h-9 w-9 place-items-center rounded-full text-pine-100/80 hover:bg-paper/10 hover:text-paper"
          aria-label="Cancel"
        >
          <XIcon />
        </button>
        <p className="text-[0.8125rem] font-medium text-pine-50">Drag the image to adjust</p>
        <div className="h-9 w-9" aria-hidden="true" />
      </div>

      <div
        className="relative touch-none select-none overflow-hidden rounded-2xl bg-ink-800"
        style={{ width: BOX, height: BOX }}
        onPointerDown={natural ? onPointerDown : undefined}
        onPointerMove={natural ? onPointerMove : undefined}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onWheel={natural ? onWheel : undefined}
      >
        <img
          ref={imgRef}
          src={objectUrl}
          alt=""
          draggable={false}
          onLoad={(e) => {
            const el = e.currentTarget;
            setNatural({ w: el.naturalWidth, h: el.naturalHeight });
          }}
          // max-w-none/max-h-none override the app-wide `img{max-width:100%;
          // height:auto}` reset (Tailwind preflight) — without them the
          // browser clamps the image to the box's width no matter what the
          // zoom math computes, so +/- visibly does nothing.
          className="absolute max-w-none max-h-none cursor-grab active:cursor-grabbing"
          style={{
            width: dispW,
            height: dispH,
            left: BOX / 2 - dispW / 2 + pan.x,
            top: BOX / 2 - dispH / 2 + pan.y,
          }}
        />
        {/* Dark surround with a circular window: a huge box-shadow spread
            from a same-sized circle, so only the circle stays undarkened.
            Tinted ink-900, not pure black, to stay in the app's warm palette. */}
        <div
          className="pointer-events-none absolute inset-0 rounded-full"
          style={{ boxShadow: "0 0 0 9999px rgba(18,33,30,0.72)" }}
        />
        <div className="pointer-events-none absolute inset-0 rounded-full ring-1 ring-inset ring-pine-200/50" />

        <div className="absolute right-2 top-1/2 flex -translate-y-1/2 flex-col overflow-hidden rounded-full border border-paper/15 bg-ink-900/70 backdrop-blur-sm">
          <button
            type="button"
            onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z + 0.2))}
            className="grid h-9 w-9 place-items-center text-paper hover:bg-paper/15"
            aria-label="Zoom in"
          >
            <PlusIcon />
          </button>
          <div className="h-px bg-paper/15" />
          <button
            type="button"
            onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z - 0.2))}
            className="grid h-9 w-9 place-items-center text-paper hover:bg-paper/15"
            aria-label="Zoom out"
          >
            <MinusIcon />
          </button>
        </div>
      </div>

      <div className="flex w-full max-w-sm justify-end pt-3">
        <button
          type="button"
          onClick={confirm}
          disabled={!natural || busy || uploading}
          data-loading={busy || uploading || undefined}
          className="grid h-12 w-12 place-items-center rounded-full bg-marigold-500 text-ink-900 shadow-lg transition hover:bg-marigold-400 active:bg-marigold-600 disabled:opacity-50"
          aria-label="Use this photo"
        >
          <CheckIcon />
        </button>
      </div>
    </div>
  );
}

function XIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3 3l10 10M13 3 3 13" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}
function PlusIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M8 2.5v11M2.5 8h11" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}
function MinusIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M2.5 8h11" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}
function CheckIcon() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3 8.5 6.5 12 13 4.5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
