import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { Plan as PlanRow, Quota } from "@/lib/types";
import { money, titleCase, toast } from "@/lib/ui";

/**
 * Plan and unlocks — one page, three former ones.
 *
 * Subscription, Extra Unlocks and Payments were separate nav items asking a
 * teacher to hold state across pages to answer one question: "can I unlock
 * this lead, and if not, what do I do?" They are now ordered to answer it:
 * where you are now, then what you could buy, then what you've paid.
 *
 * The word "token" never appears. TOKEN_SYSTEM_ENABLED is off, so the
 * economy is plan unlocks plus top-up packs, and the top-up pack's
 * `token_count` is rendered as unlocks.
 */

interface Pack {
  id: string;
  name?: string | null;
  token_count?: number | null;
  /** GST-EXCLUSIVE base. Never show this — it is not what gets charged. */
  price?: string | null;
  gst_amount?: string | null;
  /** What actually reaches Razorpay. This is the number to display. */
  final_price?: string | null;
  /** The API decides eligibility; the UI must not invent its own rule. */
  can_purchase?: boolean;
  is_active?: boolean;
}

interface Subscription {
  id: string;
  plan?: PlanRow | { name?: string } | null;
  plan_name?: string | null;
  status?: string | null;
  end_date?: string | null;
  current_period_end?: string | null;
}

interface Payment {
  id: string;
  amount?: string | null;
  status?: string | null;
  created_at: string;
  purpose?: string | null;
  description?: string | null;
}

interface Order {
  razorpay_key_id?: string;
  razorpay_order_id?: string;
  amount?: number;
  currency?: string;
}

/** Razorpay's checkout script, loaded only on this page and only once. */
function loadRazorpay(): Promise<boolean> {
  if (typeof (window as { Razorpay?: unknown }).Razorpay !== "undefined") return Promise.resolve(true);
  return new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve(true);
    s.onerror = () => resolve(false);
    document.head.appendChild(s);
  });
}

export function Plan() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);

  const quota = useQuery({
    queryKey: ["quota"],
    queryFn: () => api.get<Quota>("/subscriptions/quota/", { silent: true }),
    retry: false,
  });
  const current = useQuery({
    queryKey: ["subscription"],
    queryFn: async () => {
      const r = await api.list<Subscription>("/subscriptions/", { silent: true });
      return r.items[0] ?? null;
    },
    retry: false,
  });
  const plans = useQuery({
    queryKey: ["plans"],
    queryFn: () => api.list<PlanRow>("/subscriptions/plans/"),
  });
  const packs = useQuery({
    queryKey: ["packs"],
    queryFn: async () => {
      try {
        return await api.list<Pack>("/token-packages/", { silent: true });
      } catch {
        return { items: [] as Pack[], meta: {} };
      }
    },
    retry: false,
  });
  const payments = useQuery({
    queryKey: ["payments"],
    queryFn: async () => {
      try {
        return await api.list<Payment>("/payments/", { silent: true });
      } catch {
        return { items: [] as Payment[], meta: {} };
      }
    },
    retry: false,
  });

  const q = quota.data;
  const sub = current.data;
  const left = q?.remaining_free_leads ?? 0;
  const total = q?.total_free_leads ?? 0;
  const onPaidPlan = Boolean(sub && (sub.status ?? "").toLowerCase() === "active");

  async function checkout(body: Record<string, string>, label: string, key: string) {
    setBusy(key);
    try {
      const order = await api.post<Order>("/payments/create-order/", body, { silent: true });
      const ready = await loadRazorpay();
      const RZP = (window as { Razorpay?: new (o: unknown) => { open: () => void } }).Razorpay;

      if (!ready || !RZP || !order.razorpay_key_id || order.razorpay_key_id.includes("your_key")) {
        toast("warning", "Payments aren't set up in this environment yet. Your order was created.");
        return;
      }

      new RZP({
        key: order.razorpay_key_id,
        order_id: order.razorpay_order_id,
        amount: order.amount,
        currency: order.currency ?? "INR",
        name: "Udbhab",
        description: label,
        handler: async (resp: Record<string, string>) => {
          try {
            await api.post("/payments/verify/", {
              razorpay_order_id: resp.razorpay_order_id,
              razorpay_payment_id: resp.razorpay_payment_id,
              razorpay_signature: resp.razorpay_signature,
            });
            toast("success", "Payment received.");
            qc.invalidateQueries({ queryKey: ["quota"] });
            qc.invalidateQueries({ queryKey: ["subscription"] });
            qc.invalidateQueries({ queryKey: ["payments"] });
            qc.invalidateQueries({ queryKey: ["teacher-dashboard"] });
          } catch (e) {
            toast("error", (e as ApiError).message || "We couldn't confirm that payment.");
          }
        },
        modal: { ondismiss: () => toast("info", "Checkout closed.") },
      }).open();
    } catch (e) {
      const err = e as ApiError;
      if (err.code === "TOPUP_REQUIRES_PAID_PLAN") {
        // Only reachable if TOPUP_ELIGIBLE_PLANS is narrowed again; the
        // server's message is the accurate one, so use it rather than a
        // guess baked in here.
        toast("warning", err.message || "This pack isn't available on your plan.");
      } else {
        toast("error", err.status === 400 ? "That's no longer available." : err.message || "Couldn't start checkout.");
      }
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      {/* 1. Where you are now */}
      <section className="u-card u-card-pad">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="u-eyebrow">Your plan</p>
            <h1 className="u-h2 mt-1.5">
              {current.isLoading ? "…" : sub ? (sub.plan_name ?? (sub.plan as { name?: string })?.name ?? "Active plan") : "Free plan"}
            </h1>
            {sub?.status && <p className="u-fine mt-1">{titleCase(sub.status)}</p>}
          </div>
          <div className="text-right">
            <p className="font-display text-3xl font-bold tabular-nums leading-none text-ink-900">
              {left}<span className="text-ink-500">/{total}</span>
            </p>
            <p className="u-fine mt-1">
              unlocks left
              {typeof q?.days_until_reset === "number" && q.days_until_reset >= 0 &&
                ` · resets in ${q.days_until_reset}d`}
            </p>
          </div>
        </div>
        {total > 0 && (
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-ink-200">
            <div className="h-full rounded-full bg-pine-600 transition-[width] duration-500"
              style={{ width: `${Math.max(0, Math.min(100, (left / total) * 100))}%` }} />
          </div>
        )}
        <p className="u-fine mt-2">Unused unlocks don't roll over into next month.</p>
      </section>

      {/* 2. What you could change */}
      <section className="flex flex-col gap-4">
        <h2 className="u-h3">Plans</h2>
        {plans.isLoading ? (
          <div className="grid gap-4 sm:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-56 animate-pulse rounded-2xl bg-ink-100" />)}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-3">
            {(plans.data?.items ?? []).map((p) => {
              const isCurrent = sub != null && ((sub.plan_name ?? (sub.plan as { name?: string })?.name) === p.name);
              const unlocks = p.free_leads ?? p.base_leads ?? 0;
              return (
                <article key={p.id}
                  className={
                    "flex flex-col gap-3 rounded-2xl border-[1.5px] bg-paper p-5 shadow-lift " +
                    (isCurrent ? "border-pine-600" : p.is_featured_listing ? "border-marigold-400" : "border-ink-300")
                  }>
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-[1rem] font-semibold text-ink-900">{p.name}</h3>
                    {isCurrent && <span className="u-badge u-badge-pine shrink-0">Current</span>}
                  </div>
                  <p className="font-display text-2xl font-bold tabular-nums text-ink-900">
                    {money(p.monthly_price) ?? "Free"}
                    {p.monthly_price && <span className="ml-1 font-sans text-[0.75rem] font-medium text-ink-500">/month</span>}
                  </p>
                  <p className="u-body text-ink-700">
                    <strong className="font-semibold">{unlocks}</strong> {unlocks === 1 ? "unlock" : "unlocks"} a month
                  </p>
                  {!isCurrent && (
                    <button type="button" className="u-btn-primary u-btn-sm mt-auto"
                      data-loading={busy === p.id || undefined} disabled={busy === p.id}
                      onClick={() => checkout({ subscription_plan_id: p.id }, `${p.name} plan`, p.id)}>
                      Choose {p.name}
                    </button>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>

      {/* Top-ups — open to every plan. Capacity, not priority. */}
      {(packs.data?.items ?? []).length > 0 && (
        <section className="flex flex-col gap-4">
          <div>
            <h2 className="u-h3">Need a few more this month?</h2>
            <p className="u-fine mt-0.5">
              Any plan can buy these, and they never expire — unlike your monthly allowance.
              {!onPaidPlan && " A paid plan is what gets you seen first."}
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            {(packs.data?.items ?? []).map((pk) => {
              const count = pk.token_count ?? 0;
              // final_price is what Razorpay charges. `price` is the
              // GST-exclusive base and showing it quotes a number lower
              // than the one that leaves their account.
              const pay = money(pk.final_price ?? pk.price);
              const each = count > 1 && pk.final_price ? Number(pk.final_price) / count : null;
              const buyable = pk.can_purchase !== false;
              return (
                <article key={pk.id} className="flex flex-col gap-2 rounded-2xl border-[1.5px] border-ink-300 bg-paper p-5 shadow-lift">
                  <h3 className="text-[1rem] font-semibold text-ink-900">
                    {count} {count === 1 ? "unlock" : "unlocks"}
                  </h3>
                  <p className="font-display text-xl font-bold tabular-nums text-ink-900">{pay ?? "—"}</p>
                  <p className="u-fine">
                    {each ? `₹${Math.round(each)} each · ` : ""}GST included
                  </p>
                  <button type="button" className="u-btn-secondary u-btn-sm mt-auto"
                    disabled={!buyable || busy === pk.id} data-loading={busy === pk.id || undefined}
                    onClick={() => checkout({ token_package_id: pk.id }, `${count} extra unlocks`, pk.id)}>
                    Buy
                  </button>
                </article>
              );
            })}
          </div>
        </section>
      )}

      {/* 3. What you've paid */}
      <section className="u-card overflow-hidden">
        <div className="border-b border-ink-200 px-5 py-4">
          <h2 className="u-h3">Payments</h2>
        </div>
        {payments.isLoading ? (
          <div className="flex flex-col gap-2 p-4">
            {Array.from({ length: 2 }).map((_, i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-ink-100" />)}
          </div>
        ) : (payments.data?.items ?? []).length === 0 ? (
          <p className="u-body px-5 py-8 text-center text-ink-600">Nothing yet.</p>
        ) : (
          <ul className="divide-y divide-ink-200">
            {(payments.data?.items ?? []).map((pay) => (
              <li key={pay.id} className="flex items-center justify-between gap-3 px-5 py-3.5">
                <div className="min-w-0">
                  <p className="truncate text-[0.9375rem] font-medium text-ink-900">
                    {pay.description ?? titleCase(pay.purpose ?? "") ?? "Payment"}
                  </p>
                  <p className="u-fine mt-0.5">
                    {new Date(pay.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-[0.9375rem] font-semibold tabular-nums text-ink-900">{money(pay.amount) ?? "—"}</p>
                  {pay.status && <p className="u-fine">{titleCase(pay.status)}</p>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
