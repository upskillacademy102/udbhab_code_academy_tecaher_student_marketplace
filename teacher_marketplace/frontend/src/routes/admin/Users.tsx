import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AdminUser } from "@/lib/types";

const ROLES = ["", "student", "teacher", "admin", "superadmin"] as const;

/**
 * Admin's read-only copy of the user directory — same list endpoint the
 * Super Admin screen uses, but no Ban/Unban control: `admin_users:list`
 * grants Admin GET only (api_permissions.py), and sanctioning is Super
 * Admin only regardless.
 */
export function Users() {
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<(typeof ROLES)[number]>("");
  const [page, setPage] = useState(1);

  const users = useQuery({
    queryKey: ["admin-users", search, role, page],
    queryFn: () =>
      api.list<AdminUser>("/admin/users/", { params: { search: search || undefined, role: role || undefined, page } }),
  });
  const items = users.data?.items ?? [];

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
              {items.map((u) => (
                <tr key={u.id}>
                  <td className="px-4 py-3">
                    <Link to={`/staff/admin/users/${u.id}/`} className="font-medium text-ink-900 hover:underline">
                      {u.full_name || "(no name)"}
                    </Link>
                    <p className="text-ink-500">{u.email}</p>
                  </td>
                  <td className="px-4 py-3"><span className="u-badge u-badge-ink capitalize">{u.role}</span></td>
                  <td className="px-4 py-3">
                    <span className={u.is_active ? "u-badge u-badge-pine" : "u-badge u-badge-ink"}>
                      {u.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link to={`/staff/admin/users/${u.id}/`} className="u-btn-ghost u-btn-sm">View</Link>
                  </td>
                </tr>
              ))}
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
