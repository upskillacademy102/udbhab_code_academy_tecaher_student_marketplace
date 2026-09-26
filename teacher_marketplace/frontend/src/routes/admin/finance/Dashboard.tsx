import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type { FinanceDashboard } from "@/lib/types";

function money(v: string | number) {
  const n = typeof v === "string" ? parseFloat(v) : v;
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function Kpi({ label, count, total }: { label: string; count: number; total: string }) {
  return (
    <div className="u-card flex flex-col gap-1 p-4">
      <span className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">{label}</span>
      <span className="u-h2">{money(total)}</span>
      <span className="u-fine">{count} transaction{count === 1 ? "" : "s"}</span>
    </div>
  );
}

/**
 * Finance-department admin landing page - the "proper finance dashboard"
 * from the brief (this-week/this-month incoming & outgoing totals, top
 * Learning Partners this month, a live-ish feed of recent incoming
 * payments). Polls every 30s so new payments show up without a manual
 * refresh, matching "his dashboard will receive the information" -
 * there's no websocket/SSE infra in this codebase yet, so polling is the
 * pragmatic choice (the in-app Notification badge, apps.notifications,
 * also fires per-payment for a more immediate signal).
 */
export function Dashboard() {
  const dashQ = useQuery({
    queryKey: ["finance-dashboard"],
    queryFn: () => api.get<FinanceDashboard>("/admin/finance/dashboard/"),
    refetchInterval: 30_000,
  });

  const d = dashQ.data;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="u-h2">Finance Dashboard</h1>
        <p className="u-fine mt-1">Incoming and outgoing money across the platform.</p>
      </div>

      {dashQ.isLoading && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-2xl bg-ink-100" />
          ))}
        </div>
      )}

      {d && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Kpi label="Incoming - this week" count={d.incoming_this_week.count} total={d.incoming_this_week.total} />
          <Kpi label="Incoming - this month" count={d.incoming_this_month.count} total={d.incoming_this_month.total} />
          <Kpi label="Outgoing - this week" count={d.outgoing_this_week.count} total={d.outgoing_this_week.total} />
          <Kpi label="Outgoing - this month" count={d.outgoing_this_month.count} total={d.outgoing_this_month.total} />
        </div>
      )}

      {d && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="u-h3">Top Learning Partners this month</h2>
            <Link to="/staff/admin/finance/learning-partners/" className="u-fine underline">See all</Link>
          </div>
          {d.top_learning_partners_this_month.length === 0 && (
            <div className="u-card u-card-pad text-center text-ink-500">No commission earned yet this month.</div>
          )}
          {d.top_learning_partners_this_month.length > 0 && (
            <div className="flex flex-col gap-2">
              {d.top_learning_partners_this_month.map((p) => (
                <Link
                  key={p.learning_partner_id}
                  to={`/staff/admin/finance/learning-partners/${p.learning_partner_id}/`}
                  className="u-card u-card-pad flex items-center justify-between gap-2 hover:bg-paper-sunk"
                >
                  <span className="font-medium text-ink-900">{p.learning_partner_name || p.learning_partner_email}</span>
                  <span className="font-medium text-ink-900">{money(p.total)}</span>
                </Link>
              ))}
            </div>
          )}
        </div>
      )}

      {d && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="u-h3">Recent incoming payments</h2>
            <Link to="/staff/admin/finance/transactions/" className="u-fine underline">Full transaction log</Link>
          </div>
          {d.recent_incoming_payments.length === 0 && (
            <div className="u-card u-card-pad text-center text-ink-500">No payments yet.</div>
          )}
          {d.recent_incoming_payments.length > 0 && (
            <div className="u-card overflow-hidden">
              <table className="w-full text-left text-[0.875rem]">
                <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
                  <tr>
                    <th className="px-4 py-2.5">Teacher</th>
                    <th className="px-4 py-2.5">Amount</th>
                    <th className="px-4 py-2.5">Method</th>
                    <th className="px-4 py-2.5">Transaction ID</th>
                    <th className="px-4 py-2.5">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-100">
                  {d.recent_incoming_payments.map((p) => (
                    <tr key={p.id}>
                      <td className="px-4 py-3 text-ink-900">{p.teacher_name}</td>
                      <td className="px-4 py-3 font-medium text-ink-900">{money(p.amount)}</td>
                      <td className="px-4 py-3 text-ink-600">{p.instrument_hint || p.payment_method || "—"}</td>
                      <td className="px-4 py-3 font-mono text-ink-600">{p.transaction_id || "—"}</td>
                      <td className="px-4 py-3 text-ink-500">{new Date(p.created_at).toLocaleString("en-IN")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
