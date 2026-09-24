import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AccountSanction, AdminUser } from "@/lib/types";
import { confirmAction, sanctionLabel, toast } from "@/lib/ui";

const ROLES = ["", "student", "teacher", "admin", "superadmin"] as const;

/**
 * The full user directory, with Ban/Unban — the Super-Admin-only control
 * that plain Admin's own read-only copy of this screen (routes/admin/Users)
 * doesn't get. A user counts as "banned" when they have an AAccountSanction
 * row with active=true (fetched separately, not something AdminUserSerializer
 * exposes), not merely `is_active=false` — that flag can also be flipped by
 * the unrelated "deactivate account" control.
 */
export function Users() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<(typeof ROLES)[number]>("");
  const [page, setPage] = useState(1);

  const users = useQuery({
    queryKey: ["admin-users", search, role, page],
    queryFn: () =>
      api.list<AdminUser>("/admin/users/", { params: { search: search || undefined, role: role || undefined, page } }),
  });
  const sanctions = useQuery({
    queryKey: ["ops-sanctions", "active"],
    queryFn: () => api.list<AccountSanction>("/ops/sanctions/", { params: { active: "true" } }),
  });

  const activeByUser = new Map((sanctions.data?.items ?? []).map((s) => [s.user, s]));
  const items = users.data?.items ?? [];

  async function ban(u: AdminUser) {
    const ok = await confirmAction({
      title: `Ban ${u.full_name || u.email}?`,
      message: "They will be signed out immediately and can't log back in until unbanned.",
      confirmLabel: "Ban",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.post("/ops/sanctions/", { user_id: u.id, kind: "ban" });
      toast("success", `${u.email} has been banned.`);
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      qc.invalidateQueries({ queryKey: ["ops-sanctions"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't ban this account.");
    }
  }

  async function unban(sanction: AccountSanction) {
    const ok = await confirmAction({ title: `Unban ${sanction.user_email}?`, confirmLabel: "Unban" });
    if (!ok) return;
    try {
      await api.post(`/ops/sanctions/${sanction.id}/lift/`, {});
      toast("success", `${sanction.user_email} has been reactivated.`);
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      qc.invalidateQueries({ queryKey: ["ops-sanctions"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't unban this account.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="u-h2">Users</h1>
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="u-input w-56"
            placeholder="Search name, email, mobile"
            value={search}
            onChange={(e) => {
              setPage(1);
              setSearch(e.target.value);
            }}
          />
          <select
            className="u-select"
            value={role}
            onChange={(e) => {
              setPage(1);
              setRole(e.target.value as (typeof ROLES)[number]);
            }}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r ? r[0]!.toUpperCase() + r.slice(1) : "All roles"}
              </option>
            ))}
          </select>
        </div>
      </div>

      {users.isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(users.error as { message?: string })?.message ?? "Couldn't load users."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => users.refetch()}>Try again</button>
        </div>
      )}

      {!users.isError && (users.isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-xl bg-ink-100" />
          ))}
        </div>
      ) : (
        <div className="u-card overflow-hidden">
          <table className="w-full text-left text-[0.875rem]">
            <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
              <tr>
                <th className="px-4 py-2.5">Name</th>
                <th className="px-4 py-2.5">Role</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {items.map((u) => {
                const sanction = activeByUser.get(u.id);
                return (
                  <tr key={u.id}>
                    <td className="px-4 py-3">
                      <Link to={`/staff/superadmin/users/${u.id}/`} className="font-medium text-ink-900 hover:underline">
                        {u.full_name || "(no name)"}
                      </Link>
                      <p className="text-ink-500">{u.email}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className="u-badge u-badge-ink capitalize">{u.role}</span>
                      {u.role === "admin" && (
                        <p className="mt-1 text-ink-500">{u.admin_department_name ?? "(no department)"}</p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {sanction ? (
                        <span className="u-badge u-badge-danger">{sanctionLabel(sanction.kind)}</span>
                      ) : u.is_active ? (
                        <span className="u-badge u-badge-pine">Active</span>
                      ) : (
                        <span className="u-badge u-badge-ink">Inactive</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-2">
                        <Link to={`/staff/superadmin/users/${u.id}/`} className="u-btn-ghost u-btn-sm">View</Link>
                        {u.role !== "superadmin" &&
                          (sanction ? (
                            <button type="button" className="u-btn-ghost u-btn-sm" onClick={() => unban(sanction)}>
                              Unban
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="u-btn-ghost u-btn-sm text-danger hover:bg-danger/5"
                              onClick={() => ban(u)}
                            >
                              Ban
                            </button>
                          ))}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {items.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-ink-500">No users match this filter.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ))}

      <div className="flex items-center justify-between">
        <span className="text-[0.8125rem] text-ink-500">
          {users.data?.meta.count != null ? `${users.data.meta.count} total` : ""}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            className="u-btn-secondary u-btn-sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </button>
          <button
            type="button"
            className="u-btn-secondary u-btn-sm"
            disabled={!users.data?.meta.next}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
