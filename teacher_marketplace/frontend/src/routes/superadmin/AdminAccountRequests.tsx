import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AdminAccountRequest, AdminDepartment } from "@/lib/types";
import { confirmAction, toast } from "@/lib/ui";

/**
 * Self-service "become an Admin" requests. Approving requires picking a
 * department in the same step — there is no way to approve without one,
 * by server-side design (see AdminAccountRequestDecisionView). Distinct
 * from the legacy "Admin access requests" page under /super-admin/, which
 * approves single login attempts for admins who already exist.
 */
export function AdminAccountRequests() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<"pending" | "" | "approved" | "denied">("pending");
  const [approving, setApproving] = useState<AdminAccountRequest | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-account-requests", statusFilter],
    queryFn: () =>
      api.get<AdminAccountRequest[]>("/auth/staff/admin-account-requests/", {
        params: statusFilter ? { status: statusFilter } : {},
      }),
  });

  const items = data ?? [];

  async function deny(req: AdminAccountRequest) {
    const ok = await confirmAction({
      title: `Deny ${req.organization_name || `${req.first_name} ${req.last_name}`}'s request?`,
      message: "They won't get an admin account. This can't be undone.",
      confirmLabel: "Deny request",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.post(`/auth/staff/admin-account-requests/${req.id}/deny/`, {});
      toast("success", "Request denied.");
      qc.invalidateQueries({ queryKey: ["admin-account-requests"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't deny this request.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="u-h2">
          {isLoading ? "Loading…" : isError ? "Admin account requests" : `${items.length} request${items.length === 1 ? "" : "s"}`}
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
          <RequestCard
            key={req.id}
            req={req}
            onApprove={() => setApproving(req)}
            onDeny={() => deny(req)}
          />
        ))}
      </div>

      {approving && (
        <ApproveDialog
          req={approving}
          onClose={() => setApproving(null)}
          onApproved={() => {
            setApproving(null);
            qc.invalidateQueries({ queryKey: ["admin-account-requests"] });
          }}
        />
      )}
    </div>
  );
}

function RequestCard({
  req, onApprove, onDeny,
}: {
  req: AdminAccountRequest;
  onApprove: () => void;
  onDeny: () => void;
}) {
  const badge =
    req.status === "pending" ? "u-badge u-badge-marigold"
    : req.status === "approved" ? "u-badge u-badge-pine"
    : "u-badge u-badge-ink";

  return (
    <article className="u-card u-card-pad flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h2 className="truncate text-[0.9375rem] font-semibold text-ink-900">
            {req.organization_name || `${req.first_name} ${req.last_name}`}
          </h2>
          {req.organization_name && <span className="u-badge u-badge-ink">Learning Partner</span>}
          <span className={badge}>{req.status[0]!.toUpperCase() + req.status.slice(1)}</span>
        </div>
        <p className="u-fine mt-1">{req.email} · {req.mobile}</p>
        {req.status === "approved" && req.created_admin_account_name && (
          <p className="mt-1 text-[0.8125rem] font-medium text-pine-700">
            Account: <span className="font-mono">{req.created_admin_account_name}</span> ({req.department_name})
          </p>
        )}
        {req.status === "denied" && req.deny_reason && (
          <p className="mt-1 text-[0.8125rem] text-ink-500">Reason: {req.deny_reason}</p>
        )}
        <p className="u-fine mt-1">Requested {new Date(req.created_at).toLocaleString("en-IN")}</p>
      </div>

      {req.status === "pending" && (
        <div className="flex shrink-0 gap-2">
          <button type="button" className="u-btn-ghost u-btn-sm text-danger hover:bg-danger/5" onClick={onDeny}>
            Deny
          </button>
          <button type="button" className="u-btn-primary u-btn-sm" onClick={onApprove}>
            Approve & assign department
          </button>
        </div>
      )}
    </article>
  );
}

function ApproveDialog({
  req, onClose, onApproved,
}: {
  req: AdminAccountRequest;
  onClose: () => void;
  onApproved: () => void;
}) {
  const [departmentId, setDepartmentId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  const { data: deptData, isLoading: deptLoading } = useQuery({
    queryKey: ["staff-departments", "active"],
    queryFn: () => api.list<AdminDepartment>("/auth/staff/departments/"),
  });
  const departments = (deptData?.items ?? []).filter((d) => d.is_active);

  // Pre-select (never lock — still an explicit choice) the Learning Partner
  // department for a Learning Partner request, so the common case is one
  // click, while the server still independently enforces the match.
  useEffect(() => {
    if (departmentId || !req.organization_name) return;
    const lp = departments.find((d) => d.is_learning_partner);
    if (lp) setDepartmentId(lp.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deptData]);

  async function approve() {
    // Mandatory, no shortcut - mirrors the server, which refuses to
    // approve without department_id at all.
    if (!departmentId || submitting) return;
    setSubmitting(true);
    setFormError("");
    try {
      const res = await api.post<AdminAccountRequest>(
        `/auth/staff/admin-account-requests/${req.id}/approve/`,
        { department_id: departmentId },
      );
      toast("success", `Approved. Admin account: ${res.created_admin_account_name}`);
      onApproved();
    } catch (e) {
      setFormError((e as { message?: string })?.message ?? "Couldn't approve this request.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" role="dialog" aria-modal="true" aria-label="Approve request">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="relative w-full max-w-sm rounded-2xl border-[1.5px] border-ink-200 bg-paper p-5 shadow-raise">
        <h2 className="u-h3">Approve {req.organization_name || `${req.first_name} ${req.last_name}`}</h2>
        <p className="u-fine mt-2">
          Picking a department creates the admin account in the same step — there's no way to approve without one.
        </p>

        {formError && <p className="u-error mt-3">{formError}</p>}

        <div className="u-field mt-4">
          <label className="u-label" htmlFor="approve-dept">Department</label>
          <select
            id="approve-dept"
            className="u-select"
            value={departmentId}
            onChange={(e) => setDepartmentId(e.target.value)}
            disabled={deptLoading}
          >
            <option value="">{deptLoading ? "Loading…" : "Select a department"}</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className="u-btn-secondary" onClick={onClose}>Cancel</button>
          <button type="button" className="u-btn-primary" disabled={!departmentId || submitting} onClick={approve}>
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}
