import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AccountSanction, OpsOverview } from "@/lib/types";

/**
 * The Super Admin landing page — platform KPIs from the existing
 * `/ops/overview/` feed, plus two action-oriented panels (pending admin
 * account requests, recent automatic bans) that link straight into the
 * screens that handle them.
 */
export function Dashboard() {
  const overview = useQuery({
    queryKey: ["ops-overview"],
    queryFn: () => api.get<OpsOverview>("/ops/overview/"),
  });
  const autoBans = useQuery({
    queryKey: ["ops-sanctions", "auto", "active"],
    queryFn: () =>
      api.list<AccountSanction>("/ops/sanctions/", { params: { source_prefix: "auto_", active: "true" } }),
  });
  const fakeLeads = useQuery({
    queryKey: ["ops-fake-lead-reports", "count"],
    queryFn: () => api.get<{ results: unknown[]; count: number }>("/ops/fake-lead-reports/"),
  });

  const o = overview.data;
  const pendingRequests = o?.pending_admin_account_requests ?? 0;
  const pendingLpRequests = o?.pending_learning_partner_requests ?? 0;

  return (
    <div className="flex flex-col gap-6">
      <h1 className="u-h2">Platform Dashboard</h1>

      {overview.isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(overview.error as { message?: string })?.message ?? "Couldn't load platform stats."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => overview.refetch()}>Try again</button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
        <Tile label="Students" value={o?.users.by_role.student} loading={overview.isLoading} />
        <Tile label="Teachers" value={o?.users.by_role.teacher} loading={overview.isLoading} />
        <Tile label="Admins" value={o?.users.by_role.admin} loading={overview.isLoading} />
        <Tile label="Learning Partners" value={o?.users.by_role.learning_partner} loading={overview.isLoading} />
        <Tile label="Super Admins" value={o?.users.by_role.superadmin} loading={overview.isLoading} />
        <Tile label="Subjects" value={o?.taxonomy.subjects} loading={overview.isLoading} />
        <Tile label="Languages" value={o?.taxonomy.languages} loading={overview.isLoading} />
      </div>

      <div className="grid gap-4 lg:grid-cols-4">
        <Link
          to="/staff/superadmin/admin-account-requests/"
          className="u-card flex flex-col gap-1 p-4 transition hover:border-pine-300 hover:shadow-raise"
        >
          <span className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">Admin Provisioning</span>
          <span className="u-h2">{overview.isLoading ? "…" : pendingRequests}</span>
          <span className="text-[0.8125rem] text-ink-600">
            {pendingRequests === 1 ? "request awaiting review" : "requests awaiting review"}
          </span>
        </Link>

        <Link
          to="/staff/superadmin/learning-partners/"
          className="u-card flex flex-col gap-1 p-4 transition hover:border-pine-300 hover:shadow-raise"
        >
          <span className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">Learning Partners</span>
          <span className="u-h2">{overview.isLoading ? "…" : pendingLpRequests}</span>
          <span className="text-[0.8125rem] text-ink-600">
            {pendingLpRequests === 1 ? "request awaiting review" : "requests awaiting review"}
          </span>
        </Link>

        <Link
          to="/staff/superadmin/fake-lead-reports/"
          className="u-card flex flex-col gap-1 p-4 transition hover:border-pine-300 hover:shadow-raise"
        >
          <span className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">Fake-lead reports</span>
          <span className="u-h2">{fakeLeads.isLoading ? "…" : (fakeLeads.data?.count ?? 0)}</span>
          <span className="text-[0.8125rem] text-ink-600">students flagged, open</span>
        </Link>

        <Link
          to="/staff/superadmin/sanctions/"
          className="u-card flex flex-col gap-1 p-4 transition hover:border-pine-300 hover:shadow-raise"
        >
          <span className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">Security events (7d)</span>
          <span className="u-h2">{overview.isLoading ? "…" : (o?.security_events_7d ?? 0)}</span>
          <span className="text-[0.8125rem] text-ink-600">logins, impersonation, admin actions</span>
        </Link>
      </div>

      <div className="u-card p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="u-h3">Recent automatic bans</h2>
          <Link to="/staff/superadmin/sanctions/" className="text-[0.8125rem] font-medium text-pine-700 hover:underline">
            View all sanctions
          </Link>
        </div>
        {autoBans.isLoading ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 2 }).map((_, i) => (
              <div key={i} className="h-10 animate-pulse rounded-lg bg-ink-100" />
            ))}
          </div>
        ) : (autoBans.data?.items.length ?? 0) === 0 ? (
          <p className="text-[0.875rem] text-ink-500">No automatic bans are currently active.</p>
        ) : (
          <ul className="divide-y divide-ink-100">
            {autoBans.data!.items.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-[0.875rem]">
                <div>
                  <span className="font-medium text-ink-900">{s.user_email}</span>
                  <span className="ml-2 u-badge u-badge-ink">{s.user_role}</span>
                  <p className="text-ink-500">{s.reason || s.source}</p>
                </div>
                <Link to={`/staff/superadmin/users/${s.user}/`} className="u-btn-ghost u-btn-sm">
                  Review
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Tile({ label, value, loading }: { label: string; value: number | undefined; loading: boolean }) {
  return (
    <div className="u-card p-3.5">
      <p className="text-[0.6875rem] font-semibold uppercase tracking-wide text-ink-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-ink-900">{loading ? "…" : (value ?? 0)}</p>
    </div>
  );
}
