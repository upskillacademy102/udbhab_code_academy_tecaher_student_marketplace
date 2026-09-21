import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Admin's own dashboard is deliberately lighter than Super Admin's — Admin
 * has no `ops:*` access (platform-wide KPIs, sanctions, audit log are all
 * Super-Admin-only by omission in api_permissions.py), so this just surfaces
 * the two queues Admin actually works: teacher verification and support
 * tickets, both endpoints Admin already reads today.
 */
export function Dashboard() {
  const verification = useQuery({
    queryKey: ["admin-teacher-profiles", "pending", "count"],
    queryFn: () => api.list("/admin/teacher-profiles/", { params: { verification_status: "pending" } }),
  });
  const tickets = useQuery({
    queryKey: ["admin-support-tickets", "open", "count"],
    queryFn: () => api.list("/admin/support-tickets/"),
  });

  return (
    <div className="flex flex-col gap-6">
      <h1 className="u-h2">Your queues</h1>

      <div className="grid gap-4 sm:grid-cols-2">
        <Link
          to="/admin-portal/teachers/"
          className="u-card flex flex-col gap-1 p-4 transition hover:border-pine-300 hover:shadow-raise"
        >
          <span className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">Teacher verification</span>
          <span className="u-h2">{verification.isLoading ? "…" : (verification.data?.meta.count ?? 0)}</span>
          <span className="text-[0.8125rem] text-ink-600">profiles awaiting review</span>
        </Link>

        <Link
          to="/admin-portal/support-tickets/"
          className="u-card flex flex-col gap-1 p-4 transition hover:border-pine-300 hover:shadow-raise"
        >
          <span className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">Bugs reported</span>
          <span className="u-h2">{tickets.isLoading ? "…" : (tickets.data?.meta.count ?? 0)}</span>
          <span className="text-[0.8125rem] text-ink-600">open or assigned tickets</span>
        </Link>
      </div>

      <div className="u-card p-4">
        <h2 className="u-h3 mb-1">Users</h2>
        <p className="text-[0.875rem] text-ink-600">
          Browse every account on the platform (read-only). Role changes, activation and bans are handled by a Super Admin.
        </p>
        <Link to="/staff/admin/users/" className="u-btn-secondary u-btn-sm mt-3 inline-flex">Open the user directory</Link>
      </div>
    </div>
  );
}
