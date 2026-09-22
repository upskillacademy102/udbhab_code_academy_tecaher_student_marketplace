import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { LearningPartnerTaxonomyRequest } from "@/lib/types";
import { confirmAction, toast } from "@/lib/ui";

const STATUS_BADGE: Record<LearningPartnerTaxonomyRequest["status"], string> = {
  pending: "u-badge u-badge-marigold",
  approved: "u-badge u-badge-pine",
  denied: "u-badge u-badge-ink",
};

/**
 * Every Learning Partner's requests for a new subject or language, across
 * every partner. Approving creates the real Subject/Language row scoped to
 * that one partner (apps.accounts.admin_api.TaxonomyRequestDecisionView) -
 * never platform-wide, unlike the ordinary Subjects/Languages screens.
 */
export function TaxonomyRequests() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<"pending" | "" | "approved" | "denied">("pending");
  const [busyId, setBusyId] = useState<string | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["taxonomy-requests", statusFilter],
    queryFn: () =>
      api.get<LearningPartnerTaxonomyRequest[]>("/auth/staff/taxonomy-requests/", {
        params: statusFilter ? { status: statusFilter } : {},
      }),
  });
  const items = data ?? [];

  async function approve(req: LearningPartnerTaxonomyRequest) {
    const ok = await confirmAction({
      title: `Approve "${req.name}"?`,
      message: `This creates a real ${req.kind} visible only to ${req.learning_partner_name ?? "this partner"}'s own students/teachers.`,
      confirmLabel: "Approve",
    });
    if (!ok) return;
    setBusyId(req.id);
    try {
      await api.post(`/auth/staff/taxonomy-requests/${req.id}/approve/`, {});
      toast("success", `Approved "${req.name}".`);
      qc.invalidateQueries({ queryKey: ["taxonomy-requests"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't approve this request.");
    } finally {
      setBusyId(null);
    }
  }

  async function deny(req: LearningPartnerTaxonomyRequest) {
    const ok = await confirmAction({
      title: `Deny "${req.name}"?`,
      message: "This can't be undone.",
      confirmLabel: "Deny request",
      danger: true,
    });
    if (!ok) return;
    setBusyId(req.id);
    try {
      await api.post(`/auth/staff/taxonomy-requests/${req.id}/deny/`, {});
      toast("success", "Request denied.");
      qc.invalidateQueries({ queryKey: ["taxonomy-requests"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't deny this request.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="u-h2">
          {isLoading ? "Loading…" : isError ? "Taxonomy requests" : `${items.length} request${items.length === 1 ? "" : "s"}`}
        </h1>
        <div className="flex gap-1.5">
          {(["pending", "approved", "denied", ""] as const).map((s) => (
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
          <article key={req.id} className="u-card u-card-pad flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="u-badge u-badge-ink">{req.kind === "subject" ? "Subject" : "Language"}</span>
                <h2 className="truncate text-[0.9375rem] font-semibold text-ink-900">{req.name}</h2>
                <span className={STATUS_BADGE[req.status]}>{req.status[0]!.toUpperCase() + req.status.slice(1)}</span>
              </div>
              <p className="u-fine mt-1">Requested by {req.learning_partner_name ?? "—"}</p>
              {req.note && <p className="mt-1 text-[0.8125rem] text-ink-600">{req.note}</p>}
              {req.status === "approved" && (req.created_subject_name || req.created_language_name) && (
                <p className="mt-1 text-[0.8125rem] font-medium text-pine-700">
                  Created: {req.created_subject_name || req.created_language_name}
                </p>
              )}
              {req.status === "denied" && req.deny_reason && (
                <p className="mt-1 text-[0.8125rem] text-ink-500">Reason: {req.deny_reason}</p>
              )}
              <p className="u-fine mt-1">Requested {new Date(req.created_at).toLocaleString("en-IN")}</p>
            </div>

            {req.status === "pending" && (
              <div className="flex shrink-0 gap-2">
                <button
                  type="button"
                  className="u-btn-ghost u-btn-sm text-danger hover:bg-danger/5"
                  disabled={busyId === req.id}
                  onClick={() => deny(req)}
                >
                  Deny
                </button>
                <button
                  type="button"
                  className="u-btn-primary u-btn-sm"
                  disabled={busyId === req.id}
                  onClick={() => approve(req)}
                >
                  Approve
                </button>
              </div>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
