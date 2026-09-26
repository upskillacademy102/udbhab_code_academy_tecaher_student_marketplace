import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { FinanceTransaction } from "@/lib/types";

function money(v: string | number) {
  const n = typeof v === "string" ? parseFloat(v) : v;
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/**
 * The "bank finance log" from the brief - every incoming payment and
 * outgoing payout in one searchable/filterable table (amount, account
 * number, IFSC, transaction id, date). Account number/IFSC only exist for
 * outgoing rows (Learning Partner payouts) - Razorpay never exposes a
 * payer's bank account/IFSC for card/UPI/netbanking payments, so an
 * incoming row shows the masked instrument hint instead (see
 * apps.payments.services.PaymentService._capture_instrument_hint).
 */
export function TransactionLog() {
  const [filters, setFilters] = useState({
    direction: "",
    amount: "",
    transaction_id: "",
    account_number: "",
    ifsc_code: "",
    date_from: "",
    date_to: "",
  });

  const listQ = useQuery({
    queryKey: ["finance-transactions", filters],
    queryFn: () => api.list<FinanceTransaction>("/admin/finance/transactions/", { params: filters }),
  });

  const rows = listQ.data?.items ?? [];

  function set<K extends keyof typeof filters>(key: K, value: string) {
    setFilters((f) => ({ ...f, [key]: value }));
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="u-h2">Transactions</h1>
        <p className="u-fine mt-1">Every incoming payment and outgoing payout.</p>
      </div>

      <div className="u-card u-card-pad grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="u-field">
          <label className="u-label" htmlFor="f-direction">Direction</label>
          <select
            id="f-direction"
            className="u-select"
            value={filters.direction}
            onChange={(e) => set("direction", e.target.value)}
          >
            <option value="">All</option>
            <option value="incoming">Incoming</option>
            <option value="outgoing">Outgoing</option>
          </select>
        </div>
        <div className="u-field">
          <label className="u-label" htmlFor="f-amount">Amount</label>
          <input
            id="f-amount"
            className="u-input"
            type="number"
            step="0.01"
            value={filters.amount}
            onChange={(e) => set("amount", e.target.value)}
          />
        </div>
        <div className="u-field">
          <label className="u-label" htmlFor="f-txn">Transaction ID</label>
          <input
            id="f-txn"
            className="u-input"
            value={filters.transaction_id}
            onChange={(e) => set("transaction_id", e.target.value)}
          />
        </div>
        <div className="u-field">
          <label className="u-label" htmlFor="f-account">Account number</label>
          <input
            id="f-account"
            className="u-input"
            value={filters.account_number}
            onChange={(e) => set("account_number", e.target.value)}
            placeholder="Outgoing only"
          />
        </div>
        <div className="u-field">
          <label className="u-label" htmlFor="f-ifsc">IFSC code</label>
          <input
            id="f-ifsc"
            className="u-input"
            value={filters.ifsc_code}
            onChange={(e) => set("ifsc_code", e.target.value.toUpperCase())}
            placeholder="Outgoing only"
          />
        </div>
        <div className="u-field">
          <label className="u-label" htmlFor="f-from">From date</label>
          <input
            id="f-from"
            className="u-input"
            type="date"
            value={filters.date_from}
            onChange={(e) => set("date_from", e.target.value)}
          />
        </div>
        <div className="u-field">
          <label className="u-label" htmlFor="f-to">To date</label>
          <input
            id="f-to"
            className="u-input"
            type="date"
            value={filters.date_to}
            onChange={(e) => set("date_to", e.target.value)}
          />
        </div>
      </div>

      {listQ.isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-2xl bg-ink-100" />
          ))}
        </div>
      )}

      {!listQ.isLoading && rows.length === 0 && (
        <div className="u-card u-card-pad text-center text-ink-500">No transactions match these filters.</div>
      )}

      {rows.length > 0 && (
        <div className="u-card overflow-hidden">
          <table className="w-full text-left text-[0.875rem]">
            <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
              <tr>
                <th className="px-4 py-2.5">Direction</th>
                <th className="px-4 py-2.5">Party</th>
                <th className="px-4 py-2.5">Amount</th>
                <th className="px-4 py-2.5">Transaction ID</th>
                <th className="px-4 py-2.5">Account / IFSC</th>
                <th className="px-4 py-2.5">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {rows.map((r, i) => (
                <tr key={`${r.transaction_id}-${i}`}>
                  <td className="px-4 py-3">
                    <span className={r.direction === "incoming" ? "u-badge u-badge-pine" : "u-badge u-badge-sky"}>
                      {r.direction === "incoming" ? "Incoming" : "Outgoing"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-ink-900">{r.party}</td>
                  <td className="px-4 py-3 font-medium text-ink-900">{money(r.amount)}</td>
                  <td className="px-4 py-3 font-mono text-ink-600">{r.transaction_id || "—"}</td>
                  <td className="px-4 py-3 text-ink-600">
                    {r.account_number ? `${r.account_number} · ${r.ifsc_code}` : (r.instrument_hint || r.payment_method || "—")}
                  </td>
                  <td className="px-4 py-3 text-ink-500">{r.date ? new Date(r.date).toLocaleString("en-IN") : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
