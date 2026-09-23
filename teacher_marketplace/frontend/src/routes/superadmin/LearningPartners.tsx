import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AdminAccountRequest, LearningPartnerAdmin } from "@/lib/types";
import { confirmAction, toast } from "@/lib/ui";

const TABS = [
  { value: "active", label: "Active learning partners" },
  { value: "requests", label: "Requests" },
] as const;

/**
 * Learning Partner is its own role (role=learning_partner), not a
 * department - see apps.accounts.models.User.is_learning_partner_admin.
 * Two sub-tabs: every active partner organisation, and pending requests to
 * become one (submitted via the public /become-learning-partner/ page).
 * Distinct from AdminAccountRequests.tsx, which handles regular staff
 * department requests only - Learning Partner requests never appear there.
 */
export function LearningPartners() {
  const [tab, setTab] = useState<(typeof TABS)[number]["value"]>("active");

  return (
    <div className="flex flex-col gap-6">
      <h1 className="u-h2">Learning Partners</h1>

      <div className="flex gap-1.5">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            className="u-chip u-chip-sm"
            aria-pressed={tab === t.value}
            onClick={() => setTab(t.value)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "active" ? <ActivePartners /> : <PartnerRequests />}
    </div>
  );
}

function ActivePartners() {
  const qc = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["learning-partners"],
    queryFn: () => api.get<LearningPartnerAdmin[]>("/auth/staff/learning-partners/"),
  });

  const items = data ?? [];

  async function toggleActive(p: LearningPartnerAdmin) {
    const ok = await confirmAction({
      title: `${p.is_active ? "Deactivate" : "Reactivate"} ${p.organization_name}?`,
      message: p.is_active
        ? "They and their referred students/teachers lose access immediately."
        : "They regain access to their Learning Partner dashboard.",
      confirmLabel: p.is_active ? "Deactivate" : "Reactivate",
      danger: p.is_active,
    });
    if (!ok) return;
    try {
      await api.post(`/admin/users/${p.id}/${p.is_active ? "deactivate" : "activate"}/`, {});
      toast("success", p.is_active ? "Deactivated." : "Reactivated.");
      qc.invalidateQueries({ queryKey: ["learning-partners"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't update this account.");
    }
  }

  if (isError) {
    return (
      <div className="u-alert u-alert-error items-center justify-between">
        <span>{(error as { message?: string })?.message ?? "Couldn't load Learning Partners."}</span>
        <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-14 animate-pulse rounded-xl bg-ink-100" />
        ))}
      </div>
    );
  }

  return (
    <div className="u-card overflow-hidden">
      <table className="w-full text-left text-[0.875rem]">
        <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
          <tr>
            <th className="px-4 py-2.5">Organisation</th>
            <th className="px-4 py-2.5">Account name</th>
            <th className="px-4 py-2.5">Contact</th>
            <th className="px-4 py-2.5">Students</th>
            <th className="px-4 py-2.5">Teachers</th>
            <th className="px-4 py-2.5">Status</th>
            <th className="px-4 py-2.5" />
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-100">
          {items.map((p) => (
            <tr key={p.id}>
              <td className="px-4 py-3 font-medium text-ink-900">{p.organization_name}</td>
              <td className="px-4 py-3 font-mono text-ink-600">{p.admin_account_name}</td>
              <td className="px-4 py-3 text-ink-600">{p.email} · {p.mobile}</td>
              <td className="px-4 py-3 text-ink-600">{p.students_count}</td>
              <td className="px-4 py-3 text-ink-600">{p.teachers_count}</td>
              <td className="px-4 py-3">
                <span className={p.is_active ? "u-badge u-badge-pine" : "u-badge u-badge-ink"}>
                  {p.is_active ? "Active" : "Inactive"}
                </span>
              </td>
              <td className="px-4 py-3 text-right">
                <button
                  type="button"
                  className={
                    p.is_active
                      ? "u-btn-ghost u-btn-sm text-danger hover:bg-danger/5"
                      : "u-btn-ghost u-btn-sm"
                  }
                  onClick={() => toggleActive(p)}
                >
                  {p.is_active ? "Deactivate" : "Reactivate"}
                </button>
              </td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr>
              <td colSpan={7} className="px-4 py-10 text-center text-ink-500">No Learning Partners yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function PartnerRequests() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<"pending" | "" | "approved" | "denied">("pending");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["learning-partner-requests", statusFilter],
    queryFn: () =>
      api.get<AdminAccountRequest[]>("/auth/staff/admin-account-requests/", {
        params: { kind: "learning_partner", ...(statusFilter ? { status: statusFilter } : {}) },
      }),
  });

  const items = data ?? [];

  async function deny(req: AdminAccountRequest) {
    const ok = await confirmAction({
      title: `Deny ${req.organization_name}'s request?`,
      message: "They won't get an account. This can't be undone.",
      confirmLabel: "Deny request",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.post(`/auth/staff/admin-account-requests/${req.id}/deny/`, {});
      toast("success", "Request denied.");
      qc.invalidateQueries({ queryKey: ["learning-partner-requests"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't deny this request.");
    }
  }

  // Nothing to pick - a Learning Partner has no department (see module
  // docstring), so approving is a single step, unlike the generic staff
  // request flow in AdminAccountRequests.tsx.
  async function approve(req: AdminAccountRequest) {
    const ok = await confirmAction({
      title: `Approve ${req.organization_name}?`,
      message: "This creates their Learning Partner account immediately. This can't be undone.",
      confirmLabel: "Approve",
    });
    if (!ok) return;
    try {
      const res = await api.post<AdminAccountRequest>(
        `/auth/staff/admin-account-requests/${req.id}/approve/`,
        {},
      );
      toast("success", `Approved. Account: ${res.created_admin_account_name}`);
      qc.invalidateQueries({ queryKey: ["learning-partner-requests"] });
      qc.invalidateQueries({ queryKey: ["learning-partners"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't approve this request.");
    }
  }

  return (
    <div className="flex flex-col gap-4">
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
        {items.map((req) => {
          const badge =
            req.status === "pending" ? "u-badge u-badge-marigold"
            : req.status === "approved" ? "u-badge u-badge-pine"
            : "u-badge u-badge-ink";
          return (
            <article key={req.id} className="u-card u-card-pad flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="truncate text-[0.9375rem] font-semibold text-ink-900">{req.organization_name}</h2>
                  <span className={badge}>{req.status[0]!.toUpperCase() + req.status.slice(1)}</span>
                </div>
                <p className="u-fine mt-1">{req.email} · {req.mobile}</p>
                {req.status === "approved" && req.created_admin_account_name && (
                  <p className="mt-1 text-[0.8125rem] font-medium text-pine-700">
                    Account: <span className="font-mono">{req.created_admin_account_name}</span>
                  </p>
                )}
                {req.status === "denied" && req.deny_reason && (
                  <p className="mt-1 text-[0.8125rem] text-ink-500">Reason: {req.deny_reason}</p>
                )}
                <p className="u-fine mt-1">Requested {new Date(req.created_at).toLocaleString("en-IN")}</p>
              </div>

              {req.status === "pending" && (
                <div className="flex shrink-0 justify-end gap-2">
                  <button type="button" className="u-btn-ghost u-btn-sm text-danger hover:bg-danger/5" onClick={() => deny(req)}>
                    Deny
                  </button>
                  <button type="button" className="u-btn-success u-btn-sm" onClick={() => approve(req)}>
                    Approve
                  </button>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
