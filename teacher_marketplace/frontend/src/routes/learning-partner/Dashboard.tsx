import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { LPDashboard } from "@/lib/types";

const SITE_NAME = (window as { SITE_NAME?: string }).SITE_NAME ?? "Udbhab";

/**
 * A Learning Partner's landing page — branded with their own organisation
 * name so it's unmistakably *their* dashboard, not the platform's. Counts
 * come from /lp/dashboard/, which is already scoped to this partner's own
 * referred students/teachers server-side.
 */
export function Dashboard() {
  const overview = useQuery({
    queryKey: ["lp-dashboard"],
    queryFn: () => api.get<LPDashboard>("/lp/dashboard/"),
  });
  const o = overview.data;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">
          {overview.isLoading ? "…" : `${SITE_NAME} x ${o?.organization_name ?? ""}`}
        </p>
        <h1 className="u-h2 mt-0.5">Dashboard</h1>
      </div>

      {overview.isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(overview.error as { message?: string })?.message ?? "Couldn't load your dashboard."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => overview.refetch()}>Try again</button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-2">
        <Link
          to="/staff/learning-partner/students/"
          className="u-card flex flex-col gap-1 p-4 transition hover:border-pine-300 hover:shadow-raise"
        >
          <span className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">Students</span>
          <span className="u-h2">{overview.isLoading ? "…" : (o?.students_count ?? 0)}</span>
          <span className="text-[0.8125rem] text-ink-600">identified your organisation</span>
        </Link>

        <Link
          to="/staff/learning-partner/teachers/"
          className="u-card flex flex-col gap-1 p-4 transition hover:border-pine-300 hover:shadow-raise"
        >
          <span className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">Teachers</span>
          <span className="u-h2">{overview.isLoading ? "…" : (o?.teachers_count ?? 0)}</span>
          <span className="text-[0.8125rem] text-ink-600">identified your organisation</span>
        </Link>
      </div>
    </div>
  );
}
