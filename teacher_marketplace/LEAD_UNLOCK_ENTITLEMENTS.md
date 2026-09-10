# Lead Unlock Entitlements

How teachers pay for student contact details while `TOKEN_SYSTEM_ENABLED` is
`False`. Approved 2026-09-09. The token / wallet / package system is **pinned
and hidden, not deleted** — re-enabling is a flag flip.

---

## 1. The model

Every lead costs exactly **one unlock**. There is no per-category pricing.

| Plan | Price / 30 days | Unlocks | Advertised as | Buy top-ups | Distribution priority |
|---|---:|---:|---|---|---|
| Free | ₹0 | 4 | 4 | Yes | Last tier |
| Professional | ₹99 | 10 | 8 + **2 bonus** | Yes | Second tier |
| Elite | ₹299 | 40 | 35 + **5 bonus** | Yes | First tier |

Professional's 10 is `8 + 2`; Elite's 40 is `35 + 5`. Those bonuses used to be
one-time wallet credits (`SubscriptionPlan.bonus_tokens`); they are now folded
into the **recurring** allowance, and `bonus_tokens` is 0 on every plan.

`SubscriptionPlan.bonus_leads` records the split for display only —
`free_leads` remains the **total** and the single number the unlock workflow
spends against. `base_leads` is derived (`free_leads - bonus_leads`), and a
CHECK constraint keeps `bonus_leads <= free_leads`. **Never add `bonus_leads` on
top of `free_leads` anywhere**, or the bonus is granted twice.

### Two buckets

| | Resets | Expires | Who can spend |
|---|---|---|---|
| **Plan allowance** | every 30 days | yes — no carry-over | any plan |
| **Extra unlocks** (purchased) | never | no | any plan, Free included |

Spent **allowance first, then purchased** — always burn the expiring bucket
before the permanent one.

### Capacity vs priority

Extra unlocks are sold to **every** plan, Free included. They sell **capacity**;
the subscription sells **priority**. A Free teacher holding 50 purchased unlocks
is still last in `LeadDistributionService`'s tier cascade — Elite is offered
every lead first, then Professional, then Free — so those unlocks only ever
apply to leads that reach them. Buying unlocks never moves a teacher up a tier.

### Top-up packs

| Product | Advertised | Base | GST 18% | Charged | Per unlock |
|---|---:|---:|---:|---:|---:|
| 1 extra unlock | ₹15 | 12.71 | 2.29 | **₹15.00** | ₹15.00 |
| 5 extra unlocks | ₹49 | 41.52 | 7.47 | **₹48.99** | ₹9.80 |

> ₹49.00 exactly is **not reachable** at 18% on a two-decimal base — 41.53 gives
> 49.01, 41.52 gives 48.99, nothing lands between. We take the paisa *under* the
> advertised price. ₹15, ₹19, ₹39, ₹59 and ₹79 all land exactly if the pack
> price is ever revisited.

### Why the ladder holds

Marginal cost per unlock beyond the Free tier's 4:

| | Rate |
|---|---:|
| Elite (₹299 ÷ 36) | ₹8.31 |
| 5-pack | ₹9.80 |
| Single | ₹15.00 |
| Professional (₹99 ÷ 6) | ₹16.50 |

Elite is the cheapest unlock available, so volume buyers upgrade instead of
accumulating top-ups. Break-even for a Professional teacher is ~30 unlocks per
cycle via packs, ~23 via singles. Professional is deliberately the dearest per
unlock: it is an **access** product (tier priority, featured listing), not a
volume product.

> **Accepted risk.** With top-ups open to Free teachers, the ₹9.80/unlock pack
> undercuts Professional's ₹16.50 marginal rate — a Free teacher wanting 14
> unlocks pays ₹98 in packs against Professional's ₹99 for 10. The subscription
> is bought for *priority*, not volume: a Free teacher's purchased unlocks only
> apply to leads that survive the Elite and Professional tiers. Watch the
> subscription-vs-top-up revenue split on the admin dashboard; if paid signups
> stall, `TOPUP_ELIGIBLE_PLANS` is the lever — set it back to
> `["Professional", "Elite"]` and the paid-only fence returns with no code
> change (`TopUpRequiresPaidPlan` and its test are kept for exactly this).

---

## 2. The 30-day cycle

One clock. `SubscriptionService.subscribe` sets
`end_date = start_date + LEAD_UNLOCK_CYCLE_DAYS`, and the `MonthlyLeadQuota` row
it opens uses **exactly those bounds**. A calendar month is 28–31 days, so
billing and allowance would otherwise drift ~5 days a year and produce "my
subscription renewed but my unlocks didn't" tickets.

`LeadQuotaService.resolve_period` picks the window containing *now*:

1. the latest quota row, if now falls inside it;
2. otherwise roll forward from that row's `period_end` in **whole cycles**, so
   periods chain off the original anchor rather than restarting from whenever
   the teacher next loaded a page;
3. with no history at all, anchor to the active subscription's `start_date`,
   falling back to `teacher.created_at`.

> Deviation from the original spec: rather than creating a Free
> `TeacherSubscription` row at signup to give every teacher a clock, Free
> teachers anchor to `teacher.created_at`. Same stable per-teacher anchor, no
> extra row or signal.

### Plan-change rules

| Situation | Allowance | Usage |
|---|---|---|
| Upgrade / downgrade mid-cycle | set to the new plan's | **carries forward** |
| Cancel + resubscribe mid-cycle | set to the new plan's | **carries forward** |
| Renewal after the cycle elapsed | set to the new plan's | resets to 0 |

The carry-forward is the farming guard: without it, a teacher could subscribe to
Elite, spend all 40, cancel, resubscribe, and mint another 40 inside one month.
Carried usage is deliberately **not clamped** to the new allowance — dropping
from Elite's 40 to Professional's 10 after spending 40 leaves you at zero
remaining, rather than handing unlocks back for downgrading.

### Lapsing to Free

A lapsed teacher is treated as a Free teacher: 4 unlocks a cycle and Free's tier
priority — offered leads only after Elite and Professional. Their purchased
unlocks stay spendable, since top-ups are open to every plan. Nothing is
refunded and nothing is forfeited.

(If `TOPUP_ELIGIBLE_PLANS` is ever narrowed back to the paid plans, that same
balance becomes **frozen rather than forfeited** — it stays on the wallet and
turns spendable again on resubscribe. `can_spend_purchased_unlocks` already
implements this; nothing trips it in the current configuration.)

Disclosed at purchase:

> Extra unlocks never expire and are used only after your plan allowance runs
> out. Non-refundable.

---

## 3. Bad-lead refunds

A lead corroborated as fake or unreachable by
`TRUST_LEAD_QUALITY_CORROBORATION` (2) distinct teachers refunds every flagging
teacher, into the **purchased, never-expiring bucket** — whichever bucket the
unlock originally came from. Restoring an allowance unlock that may expire in
days is not a refund.

`TRUST_ENABLE_LEAD_QUALITY_CLAWBACK` now defaults **on**, unlike the other trust
gates: this is a promise made to teachers up front, not an optional escalation.

> **Bug this fixed.** `_clawback` used to filter `is_free_unlock=False` **and**
> `tokens_deducted > 0`. Under the allowance model almost every unlock is an
> allowance unlock (`True` / `0`), so the filter matched no rows and the gate
> silently refunded nobody while looking enabled.

Corroboration is what stops a teacher converting expiring allowance into
permanent balance on demand — keep it at 2 or higher.

---

## 4. What changed in code

| Area | Change |
|---|---|
| `config/settings/base.py` | `TOKEN_SYSTEM_ENABLED`, `LEAD_UNLOCK_CYCLE_DAYS`, `FIXED_LEAD_UNLOCK_COST`, `TOPUP_ELIGIBLE_PLANS`; clawback default → `True` |
| `subscriptions/models.py` | `MonthlyLeadQuota` re-keyed to `period_start`/`period_end` (+ `days_until_reset`, `is_current`) |
| `subscriptions/services.py` | `resolve_period`, `open_period`; 30-day subscribe window; bonus credit skipped |
| `lead_engine/unlock_service.py` | allowance → purchased → `UnlockAllowanceExhausted`; `get_unlock_token_cost` pinned to 1 |
| `matching/…/token_priority_service.py` | returns 0 — top-ups never buy ranking |
| `payments/views.py` | `teacher_can_buy_topups` on the package branch of `create-order` — passes for every plan today, re-gatable via settings |
| `payments/serializers.py` | `can_purchase` per requesting teacher |
| `trust/…/lead_quality_service.py` | clawback refunds allowance unlocks too |
| `notifications/services.py` | allowance/reset copy replaces token copy |
| `analytics/views.py` | subscription vs top-up revenue split; allowance fields on the teacher dashboard |
| Web | allowance banner partial on leads list + detail; Wallet unlinked; "Buy Tokens" → "Extra Unlocks" |

**Migrations:** `subscriptions/0006` (period re-keying — drops stale quota rows,
which are regenerable cache), `subscriptions/0007` (4 / 10 / 40,
`bonus_tokens` → 0), `subscriptions/0008` (`bonus_leads` 0 / 2 / 5 + the
`bonus_leads <= free_leads` constraint), `payments/0007` (seeds the two packs).

**Unchanged on purpose:** `EligibilityService`, lead generation, the
distribution cascade, subscription history. `LeadUnlockHistory.tokens_deducted`
records 0 for allowance unlocks and 1 for purchased ones.

---

## 5. Re-enabling the token system

1. Set `TOKEN_SYSTEM_ENABLED=True`.
2. Re-seed the original token packages (the two unlock packs stay but should be
   deactivated, not deleted — a `TokenPackage` behind a `Payment` is `PROTECT`ed).
3. Decide whether `bonus_tokens` should come back on the paid plans; the
   allowance currently prices those bonuses in, so granting both pays twice.
4. Review `LeadUnlockPricing` rows — dormant, not deleted.

`apps/subscriptions/tests/test_unlock_entitlements.py` covers both modes; the
`TOKEN_SYSTEM_ENABLED=True` cases exist specifically so the dormant path cannot
rot between now and the switch back.

---

## 6. Known trade-offs

- **Scarcity slows first contact.** Metered unlocks get deliberated; expect
  hoarding and more `LeadAssignment` rows expiring inside the 24-hour window.
- **Flat pricing removes price discrimination.** A competitive-exam lead and a
  school-tuition lead cost the same, so teachers cherry-pick the high-value ones.
- **Free-tier farming is cheaper.** Four contacts a cycle with no payment ever
  raises the multi-accounting incentive; the Phase 4/9 dedup machinery carries
  more weight now.
- **Top-ups can substitute for a subscription on price** (see the boxed note in
  §1). The defence is priority, not price — monitor the revenue split.
- **The payment rail stays live.** Top-ups mean all of Phase 7 (instrument
  signatures, cooldown, dispute holds, reconciliation) is still necessary.
