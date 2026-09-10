# Teacher Workflow Audit — 2026-08-31

Walking every task a real teacher performs on the site, in order, exactly as the
frontend calls the API. Recording every bug, hindrance, and delay. Fixing one at
a time (no parallel fixes unless tightly coupled).

## Journey steps

1. Register as a teacher (`POST /auth/register/`)
2. Log in (`POST /auth/login/`)
3. Land on dashboard (`GET /dashboard/`, `GET /leads/`, `GET /teachers/me/`)
4. Fill "Basic details" (`POST /teachers/me/`)
5. Fill "Marketplace profile" — subjects/languages/cities pickers
   (`GET /subjects/ /languages/ /location/cities/`, `POST /teachers/profile/`)
6. Set weekly availability (`GET/POST /teachers/profile/weekly-availability/`)
7. Add time-off exception (`GET/POST /teachers/profile/schedule-exceptions/`)
8. Wait for verification (admin) — re-check profile badge
9. Browse leads list (`GET /leads/`)
10. Open a lead (`GET /leads/{id}/`)
11. Check lead assignments / offers (`GET /matching/assignments/`)
12. Accept / decline an offer (`POST /matching/assignments/{id}/{accept,reject}/`)
13. Unlock a lead's contact (`POST /leads/unlock/`)
14. Check wallet + history (`GET /wallet/`, `GET /wallet/history/`)
15. Browse token packages (`GET /token-packages/`)
16. Start a token purchase (`POST /payments/create-order/`)
17. Check subscription + quota + plans (`GET /subscriptions/`, `/subscriptions/quota/`, `/subscriptions/plans/`)
18. Switch / activate a plan (`POST /subscriptions/activate/`)
19. Payment history (`GET /payments/`)
20. Notifications (`GET /notifications/`, `POST /notifications/mark-read/`)
21. Change password (`POST /auth/change-password/`)
22. Log out (`POST /auth/logout/`)

## Findings (from the full walkthrough, `journey_*@teacher.test`)

| # | Severity | Step | Symptom |
|---|----------|------|---------|
| A | **P1 bug** | 7 — Add time-off exception | `POST /teachers/profile/schedule-exceptions/` → **400** every time. Frontend sent `exception_type: "temporary_unavailability"`, model choice is `temporary_unavailable`. The whole "Add exception" feature was dead. |
| B | **P1 bug** | 18 — Switch to Free plan | `POST /subscriptions/activate/` with the Free plan → **500 INTERNAL_ERROR**. |
| C | bug? | 18 — Upgrade to paid plan | `POST /subscriptions/activate/` with a paid plan → 400 (need to confirm message is intentional; frontend uses create-order for paid, so maybe fine). |
| D | bug? | 20 — Notifications | `POST /notifications/mark-read/` with `{}` → 400. Need to confirm whether the frontend ever sends an empty body. |
| E | **perf** | 2 — Login | `POST /auth/login/` **616 ms** on success; a *failed* login measured **1496 ms**. Every teacher hits this. |
| F | **perf** | 21 — Change password | `POST /auth/change-password/` **1414 ms**. |
| G | perf | 1 — Register | `POST /auth/register/` **905 ms**. |
| — | ok | 3–17, 19 | dashboard, basic details, marketplace profile, weekly availability, verification round-trip, leads list + detail, unlock, wallet, wallet history, token packages, subscription/quota/plans reads, payments history, notifications read — all working, all < 250 ms. |

Likely E+F+G share one root cause (password-hasher work factor) → treat as one fix.

---

## Fix log

### Bug A — "Add time-off exception" always failed (FIXED ✅)
- **Root cause:** [templates/web/teacher/availability.html](templates/web/teacher/availability.html) POSTed `exception_type: "temporary_unavailability"`; the `ExceptionType` model choice is `"temporary_unavailable"` (`apps/teacher_profile/models.py:392`). DRF's `ChoiceField` rejected it → 400, surfaced to the teacher as a red toast. No other file used the wrong string.
- **Fix:** one-word correction in the template (`temporary_unavailability` → `temporary_unavailable`). The field also has a server-side default of the same value, so the form works even if the key were omitted.
- **Regression:** `apps/web/tests/test_teacher_pages.py` — (1) static check that every `exception_type:` literal in `availability.html` is a real `ExceptionType.value`; (2) API accepts the value the page now sends and echoes it back. Suite 150 → 152, all green.
- **Verified live:** rendered `/teacher/availability/` now emits `temporary_unavailable`; `POST …/schedule-exceptions/` → 201.

### Bug B — subscription activation (and token-purchase confirmation) 500'd (FIXED ✅)
Three defects in the same notification-wiring path, fixed together (identical cause):
- **B1 — `POST /subscriptions/activate/` → 500 for every plan.**
  `SubscriptionService.subscribe()` called
  `NotificationService.notify(user=…, event=…, context={…}, reference_id=…)` — but
  `notify()`'s signature is `(user, event, title, message, reference_id=…, send_email=…)`.
  `context` isn't a parameter and `title`/`message` are required → `TypeError` → 500.
  **Fix:** route through the purpose-built `NotificationService.subscription_activated(subscription)`
  wrapper, wrapped in try/except so a notification failure can't fail an
  otherwise-successful activation. (`apps/subscriptions/services.py`)
- **B2 — token-purchase confirmation had the identical broken call**
  (`apps/payments/services.py::_mark_payment_successful`, `notify(..., context={...})`).
  Worse: it ran *inside* `@transaction.atomic` **before** the wallet credit, so the
  `TypeError` rolled back the payment-success state **and** the token credit — the
  teacher pays, Razorpay confirms, tokens vanish, payment shows failed.
  **Fix:** credit the wallet first (financially-critical), then call
  `NotificationService.payment_success(payment)` best-effort in try/except.
- **B3 — `WalletService.credit()` assumes the `Wallet` row already exists**
  (it's created lazily on the first wallet-page visit). A teacher can reach checkout
  straight from the dashboard "Buy more tokens" link without ever opening the wallet
  page → `Wallet.DoesNotExist` → 500 in the same `_mark_payment_successful`.
  **Fix:** `WalletService.get_or_create_wallet(payment.teacher)` right before the credit.
- **Regression:** `apps/subscriptions/tests/test_activation.py` (3),
  `apps/payments/tests/test_payment_success.py` (2). Suite 152 → 157.
- **Verified live:** `POST /subscriptions/activate/ {plan_id: <Free>}` → 201 +
  `subscription_activated` notification; paid plan without `payment_id` → clean 400.

### Finding C — NOT a bug
`POST /subscriptions/activate/` with a paid plan and no `payment_id` → 400
"payment_id is required to activate a paid subscription plan." Correct: the
frontend routes paid plans through `create-order` → Razorpay, not `activate`.

### Finding D — NOT a bug
`POST /notifications/mark-read/` with an empty body → 400. The probe sent `{}`;
the real frontend (`templates/web/notifications.html`) **always** sends
`{notification_ids: [...]}` and early-returns when the list is empty. The 400 is
correct validation of a request the UI never makes.
- **Minor UX note (not fixed):** "Mark all read" only marks the notifications on
  the currently-loaded page (max 20), not every unread one. No backend "mark all"
  mode exists. Left as-is per "don't change behaviour without evidence" — flag for
  product.

### Findings E / F / G — auth operations were slow (FIXED ✅ — switched to Argon2id)
Owner approved the switch. `config/settings/base.py` now sets `PASSWORD_HASHERS`
with `Argon2PasswordHasher` first (then the PBKDF2 hashers, so pre-existing
passwords keep validating and are transparently re-hashed to Argon2 on the user's
next login). Added `argon2-cffi==23.1.0` to `requirements.txt`.

| Operation | Before (PBKDF2 1.2M) | After (Argon2id) |
|-----------|---------------------|------------------|
| Login | ~400–700 ms | **~130–165 ms** |
| Register | ~430–900 ms | **~170 ms** |
| Change password | ~1000–1400 ms | **~330 ms** |
| Failed login | ~1500 ms | **~130 ms** |
| First login per *existing* user | — | ~480 ms one-time (old verify + Argon2 rehash), then ~130 ms |

Security is *stronger*, not weaker: Argon2id is memory-hard (GPU/ASIC-resistant),
OWASP's first recommendation. Regression: `apps/accounts/tests/test_password_hashing.py`
(4) — Argon2 is preferred, backend installed, new hashes are Argon2, legacy
PBKDF2 hashes still verify + auto-upgrade. Suite 157 → 161.

#### (historical) root-cause notes
- `POST /auth/login/` ~400–700 ms · `POST /auth/change-password/` ~1.0–1.4 s ·
  `POST /auth/register/` ~0.4–0.9 s.
- **Root cause:** Django 5.0's default `PBKDF2PasswordHasher` runs **1,200,000
  iterations**; on this machine `_hashlib.pbkdf2_hmac` measures **~350 ms per
  hash**. Login = 1 verify (~350 ms). Change-password = 1 verify + 1 hash
  (~700 ms+). Register = 1 hash. SQL for login is only ~15 ms / 6 queries — the
  time is 100 % password hashing.
- **This is not a code bug** — it's a security/UX trade-off in Django's default.
  Not teacher-specific (hits every login on every role).
- **Options** (needs the owner's call — security-sensitive, affects all users):
  1. Switch to **Argon2** (`argon2-cffi`, Django's own recommended hasher) —
     faster *and* stronger; existing hashes upgrade transparently on next login.
     Adds one dependency.
  2. Lower PBKDF2 iterations (e.g. 600 k) — halves the time, modestly weaker.
  3. Accept it — a production server CPU is ~1.5–2× faster (~200 ms login).
  Recommendation: **option 1**.

---

## Status: teacher workflow — CLEARED
Full journey (register → profile → availability → verification → leads → unlock →
wallet → tokens → subscription → notifications → change password → logout) runs
end-to-end with no 4xx/5xx except the two intentional 400s (paid-plan activation
needs payment; empty mark-read body). Every step < 340 ms. Suite: **161 passing**.

Fixed this pass: Bug A (time-off exception), Bug B1/B2/B3 (subscription + payment
500s), E/F/G (auth latency → Argon2id).
Not fixed (flagged for product, non-blocking): "Mark all read" only clears the
loaded page.
