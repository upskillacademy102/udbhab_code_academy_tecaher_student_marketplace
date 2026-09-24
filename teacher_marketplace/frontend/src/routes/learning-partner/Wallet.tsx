import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  CommissionEarning,
  LearningPartnerBankAccount,
  LearningPartnerWallet,
  LearningPartnerWalletTransaction,
  PayoutRequest,
} from "@/lib/types";
import { toast } from "@/lib/ui";

function money(v: string | number) {
  const n = typeof v === "string" ? parseFloat(v) : v;
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

const STATUS_BADGE: Record<PayoutRequest["status"], string> = {
  pending: "u-badge u-badge-marigold",
  approved: "u-badge u-badge-sky",
  paid: "u-badge u-badge-pine",
  rejected: "u-badge u-badge-ink",
};

/**
 * A Learning Partner's commission wallet: balance, earnings history (which
 * teacher's purchase produced which commission - so the 2/3 split is
 * verifiable, not just asserted), saved bank details, and payout requests.
 * Every endpoint here is scoped to request.user server-side
 * (apps.commissions.views.LearningPartnerCommissionAPIView) - a partner can
 * never see another partner's numbers, mirroring the rest of the LP screens.
 */
export function Wallet() {
  const qc = useQueryClient();

  const walletQ = useQuery({
    queryKey: ["lp-wallet"],
    queryFn: () => api.get<LearningPartnerWallet>("/commissions/wallet/"),
  });
  const txQ = useQuery({
    queryKey: ["lp-wallet-transactions"],
    queryFn: () => api.get<LearningPartnerWalletTransaction[]>("/commissions/wallet/transactions/"),
  });
  const earningsQ = useQuery({
    queryKey: ["lp-earnings"],
    queryFn: () => api.get<CommissionEarning[]>("/commissions/earnings/"),
  });
  const bankQ = useQuery({
    queryKey: ["lp-bank-account"],
    queryFn: async () => {
      try {
        return await api.get<LearningPartnerBankAccount>("/commissions/bank-account/");
      } catch (e) {
        if ((e as { status?: number })?.status === 404) return null;
        throw e;
      }
    },
  });
  const payoutsQ = useQuery({
    queryKey: ["lp-payouts"],
    queryFn: () => api.get<PayoutRequest[]>("/commissions/payouts/"),
  });

  const wallet = walletQ.data;
  const transactions = txQ.data ?? [];
  const earnings = earningsQ.data ?? [];
  const payouts = payoutsQ.data ?? [];

  const [bankOpen, setBankOpen] = useState(false);
  const [bankForm, setBankForm] = useState({
    account_holder_name: "",
    account_number: "",
    ifsc_code: "",
    bank_name: "",
  });
  const [bankError, setBankError] = useState("");
  const [bankSubmitting, setBankSubmitting] = useState(false);

  function openBankForm() {
    setBankForm({
      account_holder_name: bankQ.data?.account_holder_name ?? "",
      account_number: bankQ.data?.account_number ?? "",
      ifsc_code: bankQ.data?.ifsc_code ?? "",
      bank_name: bankQ.data?.bank_name ?? "",
    });
    setBankError("");
    setBankOpen(true);
  }

  async function saveBank() {
    if (bankSubmitting) return;
    setBankSubmitting(true);
    setBankError("");
    try {
      await api.put("/commissions/bank-account/", bankForm);
      toast("success", "Bank account saved.");
      setBankOpen(false);
      qc.invalidateQueries({ queryKey: ["lp-bank-account"] });
    } catch (e) {
      setBankError((e as { message?: string })?.message ?? "Couldn't save bank details.");
    } finally {
      setBankSubmitting(false);
    }
  }

  const [payoutOpen, setPayoutOpen] = useState(false);
  const [payoutAmount, setPayoutAmount] = useState("");
  const [payoutError, setPayoutError] = useState("");
  const [payoutSubmitting, setPayoutSubmitting] = useState(false);

  async function requestPayout() {
    if (!payoutAmount || payoutSubmitting) return;
    setPayoutSubmitting(true);
    setPayoutError("");
    try {
      await api.post("/commissions/payouts/", { amount: payoutAmount });
      toast("success", "Payout requested.");
      setPayoutOpen(false);
      setPayoutAmount("");
      qc.invalidateQueries({ queryKey: ["lp-payouts"] });
      qc.invalidateQueries({ queryKey: ["lp-wallet"] });
    } catch (e) {
      setPayoutError((e as { message?: string })?.message ?? "Couldn't request payout.");
    } finally {
      setPayoutSubmitting(false);
    }
  }

  const hasBank = !!bankQ.data;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="u-h2">Wallet &amp; Payouts</h1>
        <p className="u-fine mt-1">
          Your commission balance from teachers who identified your organisation at sign-up.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div className="u-card flex flex-col gap-1 p-4">
          <span className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">Balance</span>
          <span className="u-h2">{walletQ.isLoading ? "…" : money(wallet?.balance ?? "0")}</span>
        </div>
        <div className="u-card flex flex-col gap-1 p-4">
          <span className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">Available to withdraw</span>
          <span className="u-h2">{walletQ.isLoading ? "…" : money(wallet?.available_balance ?? "0")}</span>
        </div>
        <div className="u-card flex flex-col gap-1 p-4">
          <span className="text-[0.75rem] font-semibold uppercase tracking-wide text-ink-500">Total earned</span>
          <span className="u-h2">
            {earningsQ.isLoading
              ? "…"
              : money(earnings.reduce((sum, e) => sum + (e.status === "active" ? parseFloat(e.partner_share) : 0), 0))}
          </span>
        </div>
      </div>

      {/* ---- Bank account ---- */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="u-h3">Bank account</h2>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={openBankForm}>
            {hasBank ? "Edit" : "Add bank account"}
          </button>
        </div>
        {!bankQ.isLoading && !hasBank && (
          <div className="u-alert u-alert-info">
            Save your bank details before you can request a payout.
          </div>
        )}
        {hasBank && bankQ.data && (
          <div className="u-card u-card-pad text-[0.875rem]">
            <p className="font-medium text-ink-900">{bankQ.data.account_holder_name}</p>
            <p className="u-fine mt-0.5">
              {bankQ.data.bank_name} · A/C {bankQ.data.account_number} · IFSC {bankQ.data.ifsc_code}
            </p>
          </div>
        )}
      </div>

      {/* ---- Payout requests ---- */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="u-h3">Payout requests</h2>
          <button
            type="button"
            className="u-btn-primary u-btn-sm"
            disabled={!hasBank}
            onClick={() => {
              setPayoutAmount("");
              setPayoutError("");
              setPayoutOpen(true);
            }}
          >
            Request payout
          </button>
        </div>
        {!payoutsQ.isLoading && payouts.length === 0 && (
          <div className="u-card u-card-pad text-center text-ink-500">No payout requests yet.</div>
        )}
        {payouts.length > 0 && (
          <div className="flex flex-col gap-2">
            {payouts.map((p) => (
              <div key={p.id} className="u-card u-card-pad flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink-900">{money(p.amount)}</span>
                  <span className={STATUS_BADGE[p.status]}>{p.status[0]!.toUpperCase() + p.status.slice(1)}</span>
                  {p.payout_reference && <span className="u-fine">Ref: {p.payout_reference}</span>}
                </div>
                <p className="u-fine">{new Date(p.created_at).toLocaleString("en-IN")}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ---- Earnings (transparency: which teacher, how it was split) ---- */}
      <div className="flex flex-col gap-3">
        <h2 className="u-h3">Earnings</h2>
        {!earningsQ.isLoading && earnings.length === 0 && (
          <div className="u-card u-card-pad text-center text-ink-500">No commission earned yet.</div>
        )}
        {earnings.length > 0 && (
          <div className="u-card overflow-hidden">
            <table className="w-full text-left text-[0.875rem]">
              <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
                <tr>
                  <th className="px-4 py-2.5">Teacher</th>
                  <th className="px-4 py-2.5">Type</th>
                  <th className="px-4 py-2.5">Your share</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {earnings.map((e) => (
                  <tr key={e.id}>
                    <td className="px-4 py-3 text-ink-900">{e.teacher_name || e.teacher_email}</td>
                    <td className="px-4 py-3 text-ink-600 capitalize">{e.payment_type.replace("_", " ")}</td>
                    <td className="px-4 py-3 font-medium text-ink-900">{money(e.partner_share)}</td>
                    <td className="px-4 py-3">
                      <span className={e.status === "active" ? "u-badge u-badge-pine" : "u-badge u-badge-ink"}>
                        {e.status === "active" ? "Active" : "Reversed"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-ink-500">{new Date(e.created_at).toLocaleDateString("en-IN")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ---- Wallet transaction ledger ---- */}
      <div className="flex flex-col gap-3">
        <h2 className="u-h3">Transaction history</h2>
        {!txQ.isLoading && transactions.length === 0 && (
          <div className="u-card u-card-pad text-center text-ink-500">No transactions yet.</div>
        )}
        {transactions.length > 0 && (
          <div className="flex flex-col gap-2">
            {transactions.map((t) => (
              <div key={t.id} className="u-card u-card-pad flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="font-medium text-ink-900 capitalize">{t.transaction_type}</span>
                  <span className="u-fine ml-2">{t.description}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className={t.transaction_type === "credit" ? "text-pine-600" : "text-red-600"}>
                    {t.transaction_type === "credit" ? "+" : "-"}
                    {money(t.amount)}
                  </span>
                  <p className="u-fine">{new Date(t.created_at).toLocaleString("en-IN")}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ---- Bank account modal ---- */}
      {bankOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center p-4" role="dialog" aria-modal="true" aria-label="Bank account">
          <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-[2px]" onClick={() => setBankOpen(false)} />
          <div className="relative w-full max-w-sm rounded-2xl border-[1.5px] border-ink-200 bg-paper p-5 shadow-raise">
            <h2 className="u-h3">Bank account</h2>
            {bankError && <p className="u-error mt-3">{bankError}</p>}
            <div className="u-field mt-4">
              <label className="u-label" htmlFor="bank-holder">Account holder name</label>
              <input
                id="bank-holder"
                className="u-input"
                autoFocus
                value={bankForm.account_holder_name}
                onChange={(e) => setBankForm({ ...bankForm, account_holder_name: e.target.value })}
              />
            </div>
            <div className="u-field mt-3">
              <label className="u-label" htmlFor="bank-number">Account number</label>
              <input
                id="bank-number"
                className="u-input"
                value={bankForm.account_number}
                onChange={(e) => setBankForm({ ...bankForm, account_number: e.target.value })}
              />
            </div>
            <div className="u-field mt-3">
              <label className="u-label" htmlFor="bank-ifsc">IFSC code</label>
              <input
                id="bank-ifsc"
                className="u-input"
                value={bankForm.ifsc_code}
                onChange={(e) => setBankForm({ ...bankForm, ifsc_code: e.target.value.toUpperCase() })}
              />
            </div>
            <div className="u-field mt-3">
              <label className="u-label" htmlFor="bank-name">Bank name</label>
              <input
                id="bank-name"
                className="u-input"
                value={bankForm.bank_name}
                onChange={(e) => setBankForm({ ...bankForm, bank_name: e.target.value })}
              />
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className="u-btn-secondary" onClick={() => setBankOpen(false)}>Cancel</button>
              <button type="button" className="u-btn-primary" disabled={bankSubmitting} onClick={saveBank}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ---- Payout request modal ---- */}
      {payoutOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center p-4" role="dialog" aria-modal="true" aria-label="Request payout">
          <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-[2px]" onClick={() => setPayoutOpen(false)} />
          <div className="relative w-full max-w-sm rounded-2xl border-[1.5px] border-ink-200 bg-paper p-5 shadow-raise">
            <h2 className="u-h3">Request payout</h2>
            <p className="u-fine mt-2">Available: {money(wallet?.available_balance ?? "0")}</p>
            {payoutError && <p className="u-error mt-3">{payoutError}</p>}
            <div className="u-field mt-4">
              <label className="u-label" htmlFor="payout-amount">Amount (₹)</label>
              <input
                id="payout-amount"
                className="u-input"
                type="number"
                min="1"
                step="0.01"
                autoFocus
                value={payoutAmount}
                onChange={(e) => setPayoutAmount(e.target.value)}
              />
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className="u-btn-secondary" onClick={() => setPayoutOpen(false)}>Cancel</button>
              <button type="button" className="u-btn-primary" disabled={payoutSubmitting || !payoutAmount} onClick={requestPayout}>
                Submit request
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
