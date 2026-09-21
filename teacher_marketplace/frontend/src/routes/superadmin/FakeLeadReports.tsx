import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { FakeLeadReport } from "@/lib/types";
import { confirmAction, toast } from "@/lib/ui";

/**
 * Every student with an open fake-lead review item - first frontend for
 * `GET /ops/fake-lead-reports/`, which previously had no UI at all. Ban/Unban
 * reuse the same /ops/sanctions/ endpoints the Users screens use; Dismiss
 * clears the review item itself (a student can be dismissed without being
 * banned, e.g. a one-off report that turned out fine) without touching any
 * sanction.
 */
export function FakeLeadReports() {
  const qc = useQueryClient();

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["ops-fake-lead-reports"],
    queryFn: () => api.get<{ results: FakeLeadReport[]; count: number }>("/ops/fake-lead-reports/"),
  });
  const items = data?.results ?? [];

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["ops-fake-lead-reports"] });
    qc.invalidateQueries({ queryKey: ["ops-sanctions"] });
  }

  async function ban(row: FakeLeadReport) {
    if (!row.student_id) return;
    const ok = await confirmAction({
      title: `Ban ${row.student_name || row.student_email}?`,
      message: "They will be signed out immediately and can't log back in until unbanned.",
      confirmLabel: "Ban",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.post("/ops/sanctions/", { user_id: row.student_id, kind: "ban", review_item_id: row.review_item_id });
      toast("success", `${row.student_email} has been banned.`);
      invalidate();
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't ban this account.");
    }
  }

  async function unban(row: FakeLeadReport) {
    if (!row.sanction) return;
    const ok = await confirmAction({ title: `Unban ${row.student_email}?`, confirmLabel: "Unban" });
    if (!ok) return;
    try {
      await api.post(`/ops/sanctions/${row.sanction.id}/lift/`, {});
      toast("success", `${row.student_email} has been reactivated.`);
      invalidate();
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't unban this account.");
    }
  }

  async function dismiss(row: FakeLeadReport) {
    const ok = await confirmAction({
      title: "Dismiss this report?",
      message: "It will be removed from this list. This does not affect any ban already in place.",
      confirmLabel: "Dismiss",
    });
    if (!ok) return;
    try {
      await api.post(`/ops/review-queue/${row.review_item_id}/resolve/`, { dismiss: true });
      toast("success", "Dismissed.");
      invalidate();
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't dismiss this report.");
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
        <div className="u-card p-6 text-center text-ink-500">No open fake-lead reports.</div>
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((row) => (
            <li key={row.review_item_id} className="u-card flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  {row.student_id ? (
                    <Link
                      to={`/staff/superadmin/users/${row.student_id}/`}
                      className="font-semibold text-ink-900 hover:underline"
                    >
                      {row.student_name || row.student_email}
                    </Link>
                  ) : (
                    <span className="font-semibold text-ink-900">{row.student_name || row.student_email}</span>
                  )}
                  {row.sanction && <span className="u-badge u-badge-danger">Banned</span>}
                  {row.account_active === false && !row.sanction && <span className="u-badge u-badge-ink">Inactive</span>}
                </div>
                <p className="mt-1 text-[0.8125rem] text-ink-500">{row.student_email}</p>
                <p className="mt-2 text-[0.875rem] text-ink-600">
                  {row.total_reports} report{row.total_reports === 1 ? "" : "s"} · {row.distinct_teachers_all} distinct teacher{row.distinct_teachers_all === 1 ? "" : "s"} overall
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
                <button type="button" className="u-btn-ghost u-btn-sm" onClick={() => dismiss(row)}>Dismiss</button>
                {row.sanction ? (
                  <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => unban(row)}>Unban</button>
                ) : (
                  <button
                    type="button"
                    className="u-btn-ghost u-btn-sm text-danger hover:bg-danger/5"
                    disabled={!row.student_id}
                    onClick={() => ban(row)}
                  >
                    Ban
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      ))}
    </div>
  );
}
