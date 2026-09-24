import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AccountSanction, AdminDepartment, AdminUser } from "@/lib/types";
import { confirmAction, sanctionLabel, toast } from "@/lib/ui";

export function UserDetail() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const [reassigning, setReassigning] = useState(false);

  const user = useQuery({
    queryKey: ["admin-user", id],
    queryFn: () => api.get<AdminUser>(`/admin/users/${id}/`),
    enabled: !!id,
  });
  const sanctions = useQuery({
    queryKey: ["ops-sanctions", "user", id],
    queryFn: () => api.list<AccountSanction>("/ops/sanctions/", { params: { user: id } }),
    enabled: !!id,
  });
  // Only an Admin has a department to reassign - fetched lazily so a
  // Student/Teacher/SuperAdmin detail page never makes this call.
  const departments = useQuery({
    queryKey: ["staff-departments"],
    queryFn: () => api.list<AdminDepartment>("/auth/staff/departments/"),
    enabled: user.data?.role === "admin",
  });

  const activeSanction = sanctions.data?.items.find((s) => s.active);

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["admin-user", id] });
    qc.invalidateQueries({ queryKey: ["admin-users"] });
    qc.invalidateQueries({ queryKey: ["ops-sanctions"] });
  }

  async function ban() {
    if (!user.data) return;
    const ok = await confirmAction({
      title: `Ban ${user.data.full_name || user.data.email}?`,
      message: "They will be signed out immediately and can't log back in until unbanned.",
      confirmLabel: "Ban",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.post("/ops/sanctions/", { user_id: user.data.id, kind: "ban" });
      toast("success", `${user.data.email} has been banned.`);
      invalidate();
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't ban this account.");
    }
  }

  async function unban() {
    if (!activeSanction) return;
    const ok = await confirmAction({ title: `Unban ${activeSanction.user_email}?`, confirmLabel: "Unban" });
    if (!ok) return;
    try {
      await api.post(`/ops/sanctions/${activeSanction.id}/lift/`, {});
      toast("success", `${activeSanction.user_email} has been reactivated.`);
      invalidate();
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't unban this account.");
    }
  }

  async function reassignDepartment(departmentId: string) {
    if (!user.data || !departmentId || departmentId === user.data.admin_department_id) return;
    setReassigning(true);
    try {
      await api.patch(`/admin/users/${user.data.id}/`, { admin_department_id: departmentId });
      toast("success", "Department updated.");
      invalidate();
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't reassign this admin's department.");
    } finally {
      setReassigning(false);
    }
  }

  if (user.isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <div className="h-8 w-48 animate-pulse rounded-lg bg-ink-100" />
        <div className="h-32 animate-pulse rounded-xl bg-ink-100" />
      </div>
    );
  }

  if (user.isError || !user.data) {
    return (
      <div className="u-alert u-alert-error items-center justify-between">
        <span>{(user.error as { message?: string })?.message ?? "Couldn't load this user."}</span>
        <Link to="/staff/superadmin/users/" className="u-btn-secondary u-btn-sm">Back to Users</Link>
      </div>
    );
  }

  const u = user.data;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to="/staff/superadmin/users/" className="text-[0.8125rem] text-ink-500 hover:underline">← All users</Link>
          <h1 className="u-h2 mt-1">{u.full_name || "(no name)"}</h1>
        </div>
        {u.role !== "superadmin" && sanctions.isSuccess &&
          (activeSanction ? (
            <button type="button" className="u-btn-secondary" onClick={unban}>Unban this account</button>
          ) : (
            <button type="button" className="u-btn-primary bg-danger text-white hover:bg-danger/90 active:bg-danger" onClick={ban}>
              Ban this account
            </button>
          ))}
        {u.role !== "superadmin" && sanctions.isError && (
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => sanctions.refetch()}>
            Couldn't confirm ban status — Retry
          </button>
        )}
      </div>

      {activeSanction && (
        <div className="u-alert u-alert-error">
          Currently {activeSanction.kind}ned{activeSanction.is_automatic ? " automatically" : ""}
          {activeSanction.reason ? `: ${activeSanction.reason}` : "."}
        </div>
      )}

      <div className="u-card grid grid-cols-1 gap-4 p-4 sm:grid-cols-2">
        <Field label="Email" value={u.email} />
        <Field label="Mobile" value={u.mobile} />
        <Field label="Role" value={u.role} className="capitalize" />
        {u.role === "admin" && <Field label="Department" value={u.admin_department_name ?? "(none)"} />}
        <Field label="Status" value={u.is_active ? "Active" : "Inactive"} />
        <Field label="Email verified" value={u.is_email_verified ? "Yes" : "No"} />
        <Field label="Mobile verified" value={u.is_mobile_verified ? "Yes" : "No"} />
        <Field label="Has an active session" value={u.has_active_session ? "Yes" : "No"} />
        <Field label="Joined" value={new Date(u.created_at).toLocaleDateString()} />
      </div>

      {u.role === "admin" && (
        <div className="u-card p-4">
          <h2 className="u-h3 mb-1">Reassign department</h2>
          <p className="mb-3 text-[0.8125rem] text-ink-500">
            Determines which admin-only actions this account can take (apps.accounts.api_permissions.DEPARTMENT_ROUTE_SCOPE).
          </p>
          {departments.isLoading ? (
            <div className="h-9 w-56 animate-pulse rounded-lg bg-ink-100" />
          ) : departments.isError ? (
            <p className="text-danger text-[0.875rem]">Couldn't load departments.</p>
          ) : (
            <select
              className="u-input w-auto"
              value={u.admin_department_id ?? ""}
              disabled={reassigning}
              onChange={(e) => reassignDepartment(e.target.value)}
            >
              <option value="" disabled>Select a department…</option>
              {(departments.data?.items ?? [])
                .filter((d) => d.is_active || d.id === u.admin_department_id)
                .map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
            </select>
          )}
        </div>
      )}

      <div className="u-card p-4">
        <h2 className="u-h3 mb-3">Sanction history</h2>
        {sanctions.isLoading ? (
          <div className="h-16 animate-pulse rounded-lg bg-ink-100" />
        ) : sanctions.isError ? (
          <p className="text-danger text-[0.875rem]">
            Couldn't load sanction history.{" "}
            <button type="button" className="underline" onClick={() => sanctions.refetch()}>Try again</button>
          </p>
        ) : (sanctions.data?.items.length ?? 0) === 0 ? (
          <p className="text-[0.875rem] text-ink-500">No bans or suspensions on record.</p>
        ) : (
          <ul className="divide-y divide-ink-100">
            {sanctions.data!.items.map((s) => (
              <li key={s.id} className="py-2.5 text-[0.875rem]">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={s.active ? "u-badge u-badge-danger" : "u-badge u-badge-ink"}>
                    {sanctionLabel(s.kind)}{s.active ? "" : " (lifted)"}
                  </span>
                  <span className="text-ink-500">{s.is_automatic ? "Automatic" : `By ${s.created_by_email || "a Super Admin"}`}</span>
                  <span className="text-ink-400">· {new Date(s.created_at).toLocaleString()}</span>
                </div>
                {s.reason && <p className="mt-1 text-ink-600">{s.reason}</p>}
                {!s.active && s.lifted_at && (
                  <p className="mt-1 text-ink-500">Lifted by {s.lifted_by_email || "a Super Admin"} on {new Date(s.lifted_at).toLocaleString()}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Field({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div>
      <p className="text-[0.6875rem] font-semibold uppercase tracking-wide text-ink-500">{label}</p>
      <p className={`mt-0.5 text-[0.9375rem] text-ink-900 ${className ?? ""}`}>{value}</p>
    </div>
  );
}
