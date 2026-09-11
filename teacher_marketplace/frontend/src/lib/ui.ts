/**
 * Bridges to the toast and confirm dialog that static/js/app.js already
 * provides and base.html already mounts.
 *
 * Reimplementing them in React would put two toast stacks on one page — the
 * Django-rendered pages still use the originals, and both layers are live at
 * the same time during the migration. One implementation, called from both.
 */

type ToastKind = "success" | "error" | "warning" | "info";

interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

declare global {
  interface Window {
    toast?: (kind: ToastKind, message: string) => void;
    confirmAction?: (opts: ConfirmOptions) => Promise<boolean>;
  }
}

export function toast(kind: ToastKind, message: string): void {
  if (typeof window.toast === "function") {
    window.toast(kind, message);
  } else if (kind === "error") {
    // Never swallow a failure just because the host page didn't load app.js.
    console.error(message);
  }
}

export async function confirmAction(opts: ConfirmOptions): Promise<boolean> {
  if (typeof window.confirmAction === "function") {
    return window.confirmAction(opts);
  }
  return window.confirm(opts.message ? `${opts.title}\n\n${opts.message}` : opts.title);
}

/** ₹1,400 — no decimals, Indian digit grouping. */
export function money(v: string | number | null | undefined): string | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  if (!Number.isFinite(n)) return null;
  return "₹" + Math.round(n).toLocaleString("en-IN");
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const first = parts[0]![0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]![0] ?? "") : "";
  return (first + last).toUpperCase();
}
