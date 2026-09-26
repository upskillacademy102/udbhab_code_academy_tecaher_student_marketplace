import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { PricingChangeRequest } from "@/lib/types";
import { confirmAction, toast } from "@/lib/ui";

function money(v: string) {
  const n = parseFloat(v);
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const TARGET_LABEL: Record<PricingChangeRequest["target_type"], string> = {
  token_package: "Token Package",
  subscription_plan: "Subscription Plan",
  lead_unlock_pricing: "Lead Unlock Pricing",
};

/**
 * Super Admin's review queue for Finance's pricing-change requests
 * (apps.finance) - Finance lost direct write access to token package /
 * subscription plan / lead-unlock pricing on 2026-09-24; this is where
 * that request is approved (applies immediately) or rejected. Mirrors
 * AdminAccountRequests.tsx's list/decide pattern in this same directory.
 */
export function PricingRequests() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<"pending" | "" | "approved" | "rejected">("pending");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["pricing-requests", statusFilter],
    queryFn: () =>
      api.get<PricingChangeRequest[]>("/admin/finance/pricing-requests/", {
        params: statusFilter ? { status: statusFilter } : {},
      }),
  });

  const items = data ?? [];

  async function decide(req: PricingChangeRequest, approve: boolean, note: string) {
    try {
      await api.post(`/admin/finance/pricing-requests/${req.id}/decide/`, { approve, note });
      toast("success", approve ? "Approved and applied." : "Rejected.");
      qc.invalidateQueries({ queryKey: ["pricing-requests"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't record this decision.");
    }
  }

  async function quickReject(req: PricingChangeRequest) {
    const ok = await confirmAction({
      title: `Reject this ${TARGET_LABEL[req.target_type]} price change?`,
      message: `${req.target_name}: ${money(req.current_value)} → ${money(req.requested_value)}. The catalog stays unchanged.`,
      confirmLabel: "Reject",
      danger: true,
    });
    if (!ok) return;
    decide(req, false, "");
  }

  async function quickApprove(req: PricingChangeRequest) {
    const ok = await confirmAction({
      title: `Approve this ${TARGET_LABEL[req.target_type]} price change?`,
      message: `${req.target_name}: ${money(req.current_value)} → ${money(req.requested_value)}. This applies immediately.`,
      confirmLabel: "Approve",
    });
    if (!ok) return;
    decide(req, true, "");
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="u-h2">
          {isLoading ? "Loading…" : `${items.length} request${items.length === 1 ? "" : "s"}`}
        </h1>
        <div className="flex gap-1.5">
          {(["pending", "approved", "rejected", ""] as const).map((s) => (
            <button
              key={s || "all"}
              type="button"
              className="u-chip u-chip-sm"
              aria-pressed={statusFilter === s}
              onClick={() => setStatusFilter(s)}
            >
              {s ? s[0]!.toUpperCase() + s.slice(1) : "All"}
            </button>
          ))}
        </div>
      </div>

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? "Couldn't load these requests."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {isLoading && (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-2xl bg-ink-100" />
          ))}
        </div>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <div className="u-card u-card-pad text-center text-ink-500">No requests here.</div>
      )}

      <div className="flex flex-col gap-3">
        {items.map((req) => (
          <RequestCard
            key={req.id}
            req={req}
            onApprove={() => quickApprove(req)}
            onReject={() => quickReject(req)}
          />
        ))}
      </div>
    </div>
  );
}

function RequestCard({ req, onApprove, onReject }: {
  req: PricingChangeRequest;
  onApprove: () => void;
  onReject: () => void;
}) {
  const badge =
    req.status === "pending" ? "u-badge u-badge-marigold"
    : req.status === "approved" ? "u-badge u-badge-pine"
    : "u-badge u-badge-ink";

  return (
    <article className="u-card u-card-pad flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="truncate text-[0.9375rem] font-semibold text-ink-900">
            {TARGET_LABEL[req.target_type]} - {req.target_name}
          </h2>
          <span className={badge}>{req.status[0]!.toUpperCase() + req.status.slice(1)}</span>
        </div>
        <p className="u-fine mt-1">
          {money(req.current_value)} → {money(req.requested_value)} · requested by {req.requested_by_email}
        </p>
        {req.note && <p className="u-fine mt-1 italic">"{req.note}"</p>}
        {req.status !== "pending" && req.decided_by_email && (
          <p className="mt-1 text-[0.8125rem] text-ink-500">
            {req.status === "approved" ? "Approved" : "Rejected"} by {req.decided_by_email}
            {req.decision_note && ` - ${req.decision_note}`}
          </p>
        )}
        <p className="u-fine mt-1">Requested {new Date(req.created_at).toLocaleString("en-IN")}</p>
      </div>

      {req.status === "pending" && (
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          <button type="button" className="u-btn-ghost u-btn-sm text-danger hover:bg-danger/5" onClick={onReject}>
            Reject
          </button>
          <button type="button" className="u-btn-success u-btn-sm" onClick={onApprove}>
            Approve
          </button>
        </div>
      )}
    </article>
  );
}
