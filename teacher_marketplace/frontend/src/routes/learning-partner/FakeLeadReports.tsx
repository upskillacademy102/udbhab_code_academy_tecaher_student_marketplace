import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { FakeLeadReport } from "@/lib/types";
import { confirmAction, toast } from "@/lib/ui";

/**
 * A Learning Partner's own students with an open fake-lead review item -
 * mirrors superadmin/FakeLeadReports.tsx's shape, scoped by
 * GET /lp/fake-lead-reports/. No Ban/Unban/Dismiss here - a Learning
 * Partner has no ban authority (see the student's own detail page for
 * "Request a ban", which reuses the ordinary report flow). The one action
 * here is Endorse: vouching that an existing teacher-raised signal is
 * real, which counts extra toward the auto-ban threshold
 * (apps.trust.services.lead_quality_service). One endorsement per student.
 */
export function FakeLeadReports() {
  const qc = useQueryClient();

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["lp-fake-lead-reports"],
    queryFn: () => api.get<{ results: FakeLeadReport[]; count: number }>("/lp/fake-lead-reports/"),
  });
  const items = data?.results ?? [];

  async function endorse(row: FakeLeadReport) {
    if (!row.student_id) return;
    const ok = await confirmAction({
      title: `Endorse the report on ${row.student_name || row.student_email}?`,
      message: "This tells the Super Admin you believe this signal is real. It adds extra weight toward an automatic ban and can't be undone.",
      confirmLabel: "Endorse",
    });
    if (!ok) return;
    try {
      await api.post(`/lp/fake-lead-reports/${row.student_id}/endorse/`, {});
      toast("success", "Endorsement recorded.");
      qc.invalidateQueries({ queryKey: ["lp-fake-lead-reports"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't record this endorsement.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="u-h2">
        {isLoading ? "Loading…" : isError ? "Fake-lead reports" : `${items.length} fake-lead report${items.length === 1 ? "" : "s"}`}
      </h1>

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? "Couldn't load fake-lead reports."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {!isError && (isLoading ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-28 animate-pulse rounded-2xl bg-ink-100" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="u-card p-6 text-center text-ink-500">No open fake-lead reports on your students.</div>
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((row) => (
            <li key={row.review_item_id} className="u-card flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  {row.student_id ? (
                    <Link
                      to={`/staff/learning-partner/students/${row.student_id}/`}
                      className="font-semibold text-ink-900 hover:underline"
                    >
                      {row.student_name || row.student_email}
                    </Link>
                  ) : (
                    <span className="font-semibold text-ink-900">{row.student_name || row.student_email}</span>
                  )}
                  {row.sanction && <span className="u-badge u-badge-danger">Banned</span>}
                  {row.account_active === false && !row.sanction && <span className="u-badge u-badge-ink">Inactive</span>}
                  {row.already_endorsed && <span className="u-badge u-badge-marigold">Endorsed by you</span>}
                </div>
                <p className="mt-1 text-[0.8125rem] text-ink-500">{row.student_email}</p>
                <p className="mt-2 text-[0.875rem] text-ink-600">
                  {row.total_reports} report{row.total_reports === 1 ? "" : "s"} · {row.distinct_teachers_all} distinct teacher{row.distinct_teachers_all === 1 ? "" : "s"} overall (weighted)
                  {" "}({row.distinct_teachers_7d} in 7d, {row.distinct_teachers_30d} in 30d)
                </p>
                {row.latest_report && (
                  <p className="text-[0.75rem] text-ink-400">
                    Latest: {row.latest_report.subject || "a lead"} with {row.latest_report.teacher_name}
                    {row.latest_report.note ? ` — "${row.latest_report.note}"` : ""}
                    {" "}({new Date(row.latest_report.at).toLocaleString()})
                  </p>
                )}
              </div>
              <div className="flex shrink-0 gap-2">
                {row.student_id && (
                  <Link to={`/staff/learning-partner/students/${row.student_id}/`} className="u-btn-ghost u-btn-sm">
                    View student
                  </Link>
                )}
                <button
                  type="button"
                  className="u-btn-primary u-btn-sm"
                  disabled={!row.student_id || row.already_endorsed}
                  onClick={() => endorse(row)}
                >
                  {row.already_endorsed ? "Endorsed" : "Endorse"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      ))}
    </div>
  );
}
