import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { PricingChangeRequest } from "@/lib/types";
import { toast } from "@/lib/ui";

function money(v: string | number) {
  const n = typeof v === "string" ? parseFloat(v) : v;
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

const STATUS_BADGE: Record<PricingChangeRequest["status"], string> = {
  pending: "u-badge u-badge-marigold",
  approved: "u-badge u-badge-pine",
  rejected: "u-badge u-badge-ink",
};

interface CatalogItem {
  id: string;
  label: string;
  currentValue: number;
  /** Rendered as ₹X when true, plain integer (e.g. token count) otherwise. */
  isCurrency: boolean;
}

/**
 * Shared "read-only catalog + request a price change" screen, used by
 * Finance's Token Packages / Subscription Plans / Lead Unlock Pricing
 * pages (frontend/src/routes/admin/finance/{TokenPackages,Plans,
 * LeadPricing}.tsx). Finance lost direct write access to all three
 * (apps.accounts.api_permissions, 2026-09-24) - this is the "Request
 * change" popup that replaces it (new price, Request/Cancel buttons),
 * per the brief. Super Admin approves/rejects from
 * routes/superadmin/PricingRequests.tsx.
 */
export function PricingCatalog<T>({
  title,
  desc,
  listPath,
  targetType,
  toItem,
}: {
  title: string;
  desc: string;
  listPath: string;
  targetType: "token_package" | "subscription_plan" | "lead_unlock_pricing";
  toItem: (row: T) => CatalogItem;
}) {
  const qc = useQueryClient();

  const listQ = useQuery({
    queryKey: ["finance-catalog", listPath],
    queryFn: () => api.get<T[]>(listPath),
  });
  const requestsQ = useQuery({
    queryKey: ["finance-pricing-requests"],
    queryFn: () => api.get<PricingChangeRequest[]>("/admin/finance/pricing-requests/"),
  });

  const items = (listQ.data ?? []).map(toItem);
  const myPendingByTarget = new Map(
    (requestsQ.data ?? [])
      .filter((r) => r.target_type === targetType && r.status === "pending")
      .map((r) => [r.target_name, r]),
  );

  const [requestFor, setRequestFor] = useState<CatalogItem | null>(null);
  const [newValue, setNewValue] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function openRequest(item: CatalogItem) {
    setRequestFor(item);
    setNewValue(String(item.currentValue));
    setNote("");
    setError("");
  }

  async function submitRequest() {
    if (!requestFor || !newValue || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      await api.post("/admin/finance/pricing-requests/", {
        target_type: targetType,
        target_id: requestFor.id,
        requested_value: newValue,
        note,
      });
      toast("success", "Price change requested. Waiting on Super Admin approval.");
      setRequestFor(null);
      qc.invalidateQueries({ queryKey: ["finance-pricing-requests"] });
    } catch (e) {
      setError((e as { message?: string })?.message ?? "Couldn't submit this request.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="u-h2">{title}</h1>
        <p className="u-fine mt-1">{desc}</p>
      </div>

      {listQ.isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-2xl bg-ink-100" />
          ))}
        </div>
      )}

      {!listQ.isLoading && items.length === 0 && (
        <div className="u-card u-card-pad text-center text-ink-500">Nothing here yet.</div>
      )}

      {items.length > 0 && (
        <div className="flex flex-col gap-2">
          {items.map((item) => {
            const pending = myPendingByTarget.get(item.label);
            return (
              <div key={item.id} className="u-card u-card-pad flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-medium text-ink-900">{item.label}</p>
                  <p className="u-fine mt-0.5">
                    {item.isCurrency ? money(item.currentValue) : item.currentValue}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {pending && (
                    <span className={STATUS_BADGE.pending}>
                      Request pending: {pending.requested_value}
                    </span>
                  )}
                  <button
                    type="button"
                    className="u-btn-secondary u-btn-sm"
                    disabled={!!pending}
                    onClick={() => openRequest(item)}
                  >
                    Request change
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {requestFor && (
        <div className="fixed inset-0 z-50 grid place-items-center p-4" role="dialog" aria-modal="true" aria-label="Request price change">
          <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-[2px]" onClick={() => setRequestFor(null)} />
          <div className="relative w-full max-w-sm rounded-2xl border-[1.5px] border-ink-200 bg-paper p-5 shadow-raise">
            <h2 className="u-h3">Request change - {requestFor.label}</h2>
            <p className="u-fine mt-2">
              Current: {requestFor.isCurrency ? money(requestFor.currentValue) : requestFor.currentValue}. Super
              Admin approves before this applies.
            </p>
            {error && <p className="u-error mt-3">{error}</p>}
            <div className="u-field mt-4">
              <label className="u-label" htmlFor="pricing-new-value">New value</label>
              <input
                id="pricing-new-value"
                className="u-input"
                type="number"
                min="0"
                step="0.01"
                autoFocus
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
              />
            </div>
            <div className="u-field mt-3">
              <label className="u-label" htmlFor="pricing-note">Note (optional)</label>
              <input
                id="pricing-note"
                className="u-input"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Why this change?"
              />
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className="u-btn-secondary" onClick={() => setRequestFor(null)}>Cancel</button>
              <button type="button" className="u-btn-primary" disabled={submitting || !newValue} onClick={submitRequest}>
                Request
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
