import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AdminAccountRequest, AdminDepartment } from "@/lib/types";
import { confirmAction, toast } from "@/lib/ui";

function displayName(req: AdminAccountRequest) {
  return `${req.first_name} ${req.last_name}`;
}

/**
 * Self-service "become an Admin" (staff department) requests. Learning
 * Partner requests are a separate concept entirely (role=learning_partner,
 * no department) with their own queue - see routes/superadmin/
 * LearningPartners.tsx - and never appear here (server-side filtered out
 * by default, see AdminAccountRequestListView).
 *
 * The requester picks a department when they submit (mandatory - see the
 * "Request admin access" page), and a Super Admin has three ways to act on
 * a pending request:
 *   - Deny
 *   - Approve — one click, straight into the requested department
 *   - Approve but assign a different department — opens a picker
 * The server independently re-checks the department on every approval path
 * (see AdminAccountRequestDecisionView) - the requested department is only
 * a UI shortcut, never trusted blindly. Distinct from the legacy "Admin
 * access requests" page under /super-admin/, which approves single login
 * attempts for admins who already exist.
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
      title: `Deny ${displayName(req)}'s request?`,
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

  async function quickApprove(req: AdminAccountRequest) {
    const ok = await confirmAction({
      title: `Approve ${displayName(req)}?`,
      message: `This creates their admin account in the ${req.requested_department_name} department. This can't be undone.`,
      confirmLabel: "Approve",
    });
    if (!ok) return;
    try {
      const res = await api.post<AdminAccountRequest>(
        `/auth/staff/admin-account-requests/${req.id}/approve/`,
        { department_id: req.requested_department },
      );
      toast("success", `Approved. Admin account: ${res.created_admin_account_name}`);
      qc.invalidateQueries({ queryKey: ["admin-account-requests"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't approve this request.");
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
            onQuickApprove={() => quickApprove(req)}
            onAssignDifferent={() => setApproving(req)}
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
  req, onQuickApprove, onAssignDifferent, onDeny,
}: {
  req: AdminAccountRequest;
  onQuickApprove: () => void;
  onAssignDifferent: () => void;
  onDeny: () => void;
}) {
  const badge =
    req.status === "pending" ? "u-badge u-badge-marigold"
    : req.status === "approved" ? "u-badge u-badge-pine"
    : "u-badge u-badge-ink";

  // The one-click "Approve" shortcut only shows when there's actually a
  // requested department to approve into (older, pre-department-dropdown
  // rows have none) - otherwise only "assign a department" is offered.
  const canQuickApprove = req.status === "pending" && Boolean(req.requested_department);

  return (
    <article className="u-card u-card-pad flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="truncate text-[0.9375rem] font-semibold text-ink-900">
            {displayName(req)}
          </h2>
          <span className={badge}>{req.status[0]!.toUpperCase() + req.status.slice(1)}</span>
          {req.requested_department_name ? (
            <span className="u-callout">Wants: {req.requested_department_name}</span>
          ) : req.status === "pending" ? (
            <span className="u-fine italic">No department requested</span>
          ) : null}
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
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          <button type="button" className="u-btn-ghost u-btn-sm text-danger hover:bg-danger/5" onClick={onDeny}>
            Deny
          </button>
          {canQuickApprove && (
            <button type="button" className="u-btn-success u-btn-sm" onClick={onQuickApprove}>
              Approve
            </button>
          )}
          <button type="button" className="u-btn-primary u-btn-sm" onClick={onAssignDifferent}>
            Approve but assign different department
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

  // Pre-select (never lock — still an explicit choice) the requested
  // department, so the common case is one click, while the server still
  // independently re-validates it.
  useEffect(() => {
    if (departmentId || !req.requested_department) return;
    if (departments.some((d) => d.id === req.requested_department)) {
      setDepartmentId(req.requested_department);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deptData]);

  async function approve() {
    // Mandatory, no shortcut - mirrors the server, which refuses to
    // approve without department_id at all.
    if (!departmentId || submitting) return;
    const dept = departments.find((d) => d.id === departmentId);
    const ok = await confirmAction({
      title: `Approve ${displayName(req)} into ${dept?.name ?? "this department"}?`,
      message: "This creates their admin account immediately. This can't be undone.",
      confirmLabel: "Approve",
    });
    if (!ok) return;
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
        <h2 className="u-h3">Approve {displayName(req)}</h2>
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
