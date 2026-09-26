import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import type { LearningPartnerCommissionDetail, LearningPartnerCommissionSummary } from "@/lib/types";

function money(v: string | number) {
  const n = typeof v === "string" ? parseFloat(v) : v;
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/**
 * This month's commission owed to each Learning Partner - clicking one
 * opens the per-teacher breakdown (which teacher's purchases produced how
 * much of it), per the brief: "the learning partner panel will first
 * contain the amount that they will receive at the end of the month...
 * clicking on that [opens] all teacher name and the amount they have
 * purchased." The actual payout request/approval flow is unchanged and
 * lives at /admin-portal/payouts/ (apps.commissions) - this page is
 * read-only visibility into what's accruing, not where a payout is
 * requested or approved.
 */
export function LearningPartners() {
  const listQ = useQuery({
    queryKey: ["finance-lp-summary"],
    queryFn: () => api.get<LearningPartnerCommissionSummary[]>("/admin/finance/learning-partners/"),
  });
  const rows = listQ.data ?? [];
  const navigate = useNavigate();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="u-h2">Learning Partners</h1>
        <p className="u-fine mt-1">This month's commission total per partner. Click one for the per-teacher breakdown.</p>
      </div>

      {listQ.isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-2xl bg-ink-100" />
          ))}
        </div>
      )}

      {!listQ.isLoading && rows.length === 0 && (
        <div className="u-card u-card-pad text-center text-ink-500">No commission earned yet this month.</div>
      )}

      {rows.length > 0 && (
        <div className="flex flex-col gap-2">
          {rows.map((p) => (
            <button
              key={p.learning_partner_id}
              type="button"
              className="u-card u-card-pad flex items-center justify-between gap-2 text-left hover:bg-paper-sunk"
              onClick={() => navigate(`/staff/admin/finance/learning-partners/${p.learning_partner_id}/`)}
            >
              <div>
                <p className="font-medium text-ink-900">{p.learning_partner_name || p.learning_partner_email}</p>
                <p className="u-fine mt-0.5">{p.teacher_count} teacher{p.teacher_count === 1 ? "" : "s"}</p>
              </div>
              <span className="text-[1.0625rem] font-semibold text-ink-900">{money(p.total)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function LearningPartnerDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const detailQ = useQuery({
    queryKey: ["finance-lp-detail", id],
    queryFn: () => api.get<LearningPartnerCommissionDetail[]>(`/admin/finance/learning-partners/${id}/`),
    enabled: !!id,
  });
  const rows = detailQ.data ?? [];
  const total = rows.reduce((sum, r) => sum + parseFloat(r.total), 0);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="u-h2">This month's breakdown</h1>
          <p className="u-fine mt-1">Which teacher's purchases produced this partner's commission.</p>
        </div>
        <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => navigate("/staff/admin/finance/learning-partners/")}>
          Back
        </button>
      </div>

      {!detailQ.isLoading && rows.length > 0 && (
        <div className="u-card u-card-pad flex items-center justify-between">
          <span className="font-medium text-ink-900">Total this month</span>
          <span className="text-[1.0625rem] font-semibold text-ink-900">{money(total)}</span>
        </div>
      )}

      {detailQ.isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-2xl bg-ink-100" />
          ))}
        </div>
      )}

      {!detailQ.isLoading && rows.length === 0 && (
        <div className="u-card u-card-pad text-center text-ink-500">No commission from this partner yet this month.</div>
      )}

      {rows.length > 0 && (
        <div className="u-card overflow-hidden">
          <table className="w-full text-left text-[0.875rem]">
            <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
              <tr>
                <th className="px-4 py-2.5">Teacher</th>
                <th className="px-4 py-2.5">Purchases</th>
                <th className="px-4 py-2.5">Commission</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {rows.map((r) => (
                <tr key={r.teacher_id}>
                  <td className="px-4 py-3 text-ink-900">{r.teacher_name || r.teacher_email}</td>
                  <td className="px-4 py-3 text-ink-600">{r.purchase_count}</td>
                  <td className="px-4 py-3 font-medium text-ink-900">{money(r.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
