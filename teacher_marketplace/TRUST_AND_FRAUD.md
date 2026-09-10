# Trust & Fraud-Prevention Program

Identity verification + fraud controls across every role. Built in 10
checkpointed phases (Aug–Sep 2026); the phase-by-phase build log is at the
bottom of this file. Full plan: `~/.claude/plans/wiggly-inventing-shore.md`.

**Ground rules (held for every phase):** every enforcement gate is behind
its own `settings` flag, **default OFF**. External services (SMS, gov-ID,
liveness, phone-reachability, penny-drop, CAPTCHA, GeoIP, ML classifier) go
through pluggable providers with working dev adapters — going live = add
vendor keys + one adapter class, nothing else. The full test suite stays
green with **all flags OFF** (byte-for-byte prior behaviour) and each flag
has its own `override_settings` ON coverage. Suite: **283 → 484**.

---

## 1. Architecture

```
apps/trust/
  providers/        base.py (abstract) + console|stub|manual|regex adapters + get_provider(kind)
  models.py         TrustProfile (per-user scores/state) · ManualReviewItem (the one queue)
                    OTPChallenge · SensitiveChangeRequest · IdentitySignature/DuplicateSignal
                    TeacherVerificationItem · RiskSignal · LeadQualityRating · RequirementContactCheck
                    ContentFlag · UserReport · UserBlock
  gates.py          DRF permission classes - RequireVerified{Email,Mobile,ToPostRequirement},
                    NotFlaggedAsDuplicate, NotRiskSuspended  (each a no-op unless its flag is on)
  matching_support  apply_teacher_gate / exclude_blocked_teachers / *_map helpers
                    (the ONLY place matching/search read trust state)
  services/         otp · sensitive_change · captcha · dedupe · verification · risk · anomaly
                    requirement_velocity · lead_quality · reachability · content_scan · report_block
  tasks.py          apply_due_sensitive_changes · recompute_teacher_verification_scores · recompute_risk_scores

apps/reviews/       Review + ReviewIntegrityService (Phase 8c)
apps/payments/      risk.py · disputes.py · refunds.py · reconciliation.py · cooldown.py (Phase 7)
apps/wallet/        WalletHold + spendable-balance enforcement (Phase 7d)
apps/ops/           review-queue + risk API + web page (Phase 9c) - Super-Admin only
```

**The signal → risk → enforcement pipeline**

1. A negative event anywhere calls `RiskService.add_signal(user, kind=…, weight=…)`.
2. `RiskService.recompute` sums **active** signal weights → `TrustProfile.risk_score`
   (capped 100) → `risk_state`: `< 20 normal`, `20–49 limited`, `50–79 review`,
   `>= 80 suspended`. Crossing into `review`+ opens a `RISK_ESCALATION`
   review-queue item (always — ops sees it even with auto-actions off).
3. Enforcement reads the state **only when `TRUST_ENABLE_RISK_AUTO_ACTIONS` is on**:
   `suspended` → `NotRiskSuspended` blocks paid/lead/review actions; `limited`/
   `review` → shadow-limited (requirements HELD) + a bounded search/lead down-rank.
4. Everything else (OTP gates, teacher floor, reachability, dispute freeze,
   content moderation, blocking) is an independent gate behind its own flag,
   feeding the same `RiskSignal` table and the same `ManualReviewItem` queue.

---

## 2. Feature-flag reference

All in `config/settings/base.py` via `decouple.config(…, default=False)`,
pinned OFF in `config/settings/test.py`. Flip per-flag once its journey is
proven in staging.

| Flag | Gates | Phase | Notes / depends on |
|---|---|---|---|
| `TRUST_REQUIRE_EMAIL_VERIFICATION` | `UnlockLeadView`, `CreateOrderView` need a verified email | 1 | needs the OTP endpoints live |
| `TRUST_REQUIRE_MOBILE_VERIFICATION` | same, verified mobile | 1 | needs a real SMS provider |
| `TRUST_REQUIRE_STUDENT_VERIFIED_TO_POST` | `POST /student-requirements/` needs email+mobile verified | 6a | both of the above |
| `TRUST_ENABLE_STEP_UP_REVERIFICATION` | email/mobile change → OTP + cooldown window | 2 | — |
| `TRUST_ENABLE_CAPTCHA` | register/login/admin-login demand a CAPTCHA token once a client fingerprint has cycled ≥ `TRUST_CAPTCHA_SWITCH_THRESHOLD` (10) accounts/24h | 3 | needs a real CAPTCHA provider + client widget |
| `TRUST_ENABLE_DEDUP_BLOCKING` | duplicate-flagged accounts blocked from paid/lead actions pending review | 4 | dedup detection runs regardless; this only enforces |
| `TRUST_TEACHER_FLOOR_FOR_LEADS` | lead/search candidate gate = profile-complete + email + mobile verified (+ reachable), not the old admin `VERIFIED` flag | 5d | run `manage.py recompute_verification_scores` first |
| `TRUST_VERIFICATION_SCORE_AFFECTS_RANKING` | 0–1 `verification_score` biases lead-tier ordering + search sort | 5d | same |
| `TRUST_ENABLE_REQUIREMENT_VELOCITY` | per-day / max-open requirement caps (429); shadow-limited students' requirements HELD; abandonment risk signal | 6c | — |
| `TRUST_ENABLE_PHONE_REACHABILITY_CHECK` | unlock blocked (uncharged) if the student's number isn't reachable | 6b | needs a real reachability provider |
| `TRUST_ENABLE_LEAD_QUALITY_CLAWBACK` | ≥ `TRUST_LEAD_QUALITY_CORROBORATION` (2) teachers rating a student's leads fake/unreachable → token refund to them | 6d | the rating endpoint + signal work regardless |
| `TRUST_ENABLE_PAYMENT_RISK_CHECKS` | instrument-reuse / amount-spike / failed-burst signals **and** the dispute→WalletHold token freeze | 7c/7d | — |
| `TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN` | first `TRUST_NEW_ACCOUNT_COOLDOWN_HOURS` (24): single-order cap `TRUST_NEW_ACCOUNT_MAX_PURCHASE` (2000) + freshly bought tokens held | 7g | — |
| `TRUST_ENABLE_CONTACT_LEAKAGE_SCAN` | profile/review text scanned; hits → `moderation_status=HELD` (hidden from search, visible to the teacher) | 8a/8b | regex provider ships; swap for ML later |
| `TRUST_ENABLE_REVIEW_SYSTEM` | the whole `apps/reviews` surface (endpoints 404 while off); `TeacherProfile.rating` becomes review-derived | 8c | — |
| `TRUST_ENABLE_USER_BLOCKING` | `UserBlock` rows filter search + lead distribution both ways | 8d | report + block CRUD always work |
| `TRUST_ENABLE_ANOMALY_ALERTS` | login anomaly checks (new country/device, accounts-per-device) + refund-velocity → signals + queue items | 9b | needs a real GeoIP provider |
| `TRUST_ENABLE_RISK_AUTO_ACTIONS` | the risk engine actually *acts* — `is_suspended` gates + ranking penalty. Off = recommend-only into the queue | 9a | flip this **last**, after the queue is being worked |
| `TRUST_ENABLE_SUSPENSION_APPEALS` | a risk-suspended user is redirected to `/suspended/` and can file an in-app appeal (opens a `SUSPENSION_APPEAL` review item; resolving it clears the user's risk signals and lifts the suspension, dismissing denies it). Off = the page shows only a `SUPPORT_EMAIL` mailto link | post-10 | pair with `TRUST_ENABLE_RISK_AUTO_ACTIONS`; needs `SUPPORT_EMAIL` set (and optionally `TRUST_APPEALS_NOTIFY_EMAIL`) |

Providers: `TRUST_SMS_PROVIDER=console`, `TRUST_ID_PROVIDER=manual`,
`TRUST_LIVENESS_PROVIDER=manual`, `TRUST_PHONE_REACHABILITY_PROVIDER=stub`,
`TRUST_PENNY_DROP_PROVIDER=manual`, `TRUST_CAPTCHA_PROVIDER=stub`,
`TRUST_CONTENT_CLASSIFIER_PROVIDER=regex`, `TRUST_GEOIP_PROVIDER=stub`.

---

## 3. Going live — provider swap guide

For each: write one class implementing the `apps/trust/providers/base.py`
interface, register it in `_REGISTRY` in `providers/__init__.py`, set the
`TRUST_<KIND>_PROVIDER` env var. No other code changes.

| Kind | Interface | Real options |
|---|---|---|
| `sms` | `send(to, body)` | MSG91 / Twilio / Kaleyra (Indian DLT-registered sender) |
| `captcha` | `verify(token, remote_ip)` | Cloudflare Turnstile / reCAPTCHA v3 (+ add the widget to the register/login pages) |
| `phone_reachability` | `check(number)` | Twilio Lookup / a telco HLR-lookup vendor |
| `id` | `verify(full_name, dob, document_type, document_ref)` | Signzy / IDfy / Digilocker (Aadhaar/PAN/DL) |
| `liveness` | `check(selfie_ref, id_photo_ref)` | AWS Rekognition / a KYC vendor's face-match |
| `penny_drop` | `verify(account_number, ifsc, expected_name)` | Razorpay / Cashfree bank-account verification (only when payouts ship) |
| `content_classifier` | `classify(text)` | a hosted moderation model; keep the regex as a cheap pre-filter |
| `geoip` | `lookup(ip)` | MaxMind GeoLite2 (bundled DB, no per-call cost) / ipinfo |

Also (dashboard-only, no code): enable **Razorpay Thirdwatch + 3-D Secure**,
and subscribe the webhook to `payment.dispute.*` + `refund.*` events.

---

## 4. Recommended activation order (production)

Turn flags on in waves; leave each wave for a week and watch the review
queue + support volume before the next.

1. **Identity, low-friction.** `TRUST_SMS_PROVIDER`/`TRUST_CAPTCHA_PROVIDER`
   real → `TRUST_ENABLE_STEP_UP_REVERIFICATION`, `TRUST_ENABLE_CAPTCHA`.
   (Nothing blocks existing users; only sensitive changes / bot-like clients.)
2. **Contact verification.** `TRUST_REQUIRE_EMAIL_VERIFICATION`,
   `TRUST_REQUIRE_MOBILE_VERIFICATION`, then `TRUST_REQUIRE_STUDENT_VERIFIED_TO_POST`.
   Communicate the change; expect a verification drop-off.
3. **Teacher quality.** `manage.py recompute_verification_scores`, then
   `TRUST_TEACHER_FLOOR_FOR_LEADS` + `TRUST_VERIFICATION_SCORE_AFFECTS_RANKING`.
   Watch lead-fill rate.
4. **Anti-abuse, non-punitive.** `TRUST_ENABLE_DEDUP_BLOCKING`,
   `TRUST_ENABLE_REQUIREMENT_VELOCITY`, `TRUST_ENABLE_CONTACT_LEAKAGE_SCAN`,
   `TRUST_ENABLE_USER_BLOCKING`, `TRUST_ENABLE_ANOMALY_ALERTS`. Each only
   flags / queues at this point (auto-actions still off).
5. **Money.** reachability provider real → `TRUST_ENABLE_PHONE_REACHABILITY_CHECK`;
   then `TRUST_ENABLE_PAYMENT_RISK_CHECKS`, `TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN`,
   `TRUST_ENABLE_LEAD_QUALITY_CLAWBACK`. Reconciliation (`reconcile-payments`
   beat) is always on — check its `ReconciliationRun` output first.
6. **Reviews.** `TRUST_ENABLE_REVIEW_SYSTEM` once there's a moderation rota.
7. **Auto-enforcement.** `TRUST_ENABLE_RISK_AUTO_ACTIONS` — **only** once
   the `RISK_ESCALATION` queue is being worked daily and false-positive
   rates from waves 4–5 are understood.

---

## 5. Residual risks / known gaps

- **Weak fingerprinting.** Device/CAPTCHA/anomaly checks hash coarse headers
  + IP (no JS fingerprint lib). Good for "one client, many accounts", not for
  unique-device identity. A determined actor rotating IPs/UAs evades them.
- **GeoIP anomaly needs history.** New-country only fires once the account has
  a `known_countries` entry — the first login from anywhere is never flagged.
- **Risk signals don't decay** unless a caller passes `expires_at` (none
  currently do). A user who trips `suspended` stays there until an admin
  resolves the `RISK_ESCALATION` item (or grants a suspension appeal — see
  below) — deliberate, but there's no auto-lift.
- **Suspension appeal** (`TRUST_ENABLE_SUSPENSION_APPEALS`): a suspended user
  is redirected to `/suspended/` and can file one appeal, which opens a
  `SUSPENSION_APPEAL` review item. Ops **resolves** it to grant (clears the
  user's active `RiskSignal`s + recomputes → suspension lifts) or **dismisses**
  to deny. Still no in-app appeal for `limited`/`review` states, and granting
  clears *all* active signals rather than the specific disputed one.
- **Fungible tokens.** Refund/chargeback eligibility (7e) and the dispute
  freeze (7d) can only act on the wallet's *current* spendable balance;
  tokens already spent before a dispute are recorded as a shortfall, not
  recovered.
- **No real doc storage yet.** `id`/`liveness` providers are `manual` stubs;
  `TeacherVerificationItem.evidence_ref` holds a client-supplied reference
  string, not a stored file. The retention table at the end of this file
  assumes a real storage-backed provider is wired before those flags are
  enabled.
- **Reconciliation is internal-only in dev.** With placeholder Razorpay keys
  it checks Payment ⇔ WalletTransaction consistency but not the gateway;
  the gateway leg only runs with real keys.
- **`apps/ops` review queue is Super-Admin only.** Admin-role staff work the
  queue through Django admin (`ManualReviewItem`); a role grant in
  `_RULES` would open the API/web queue to them.

---

## Phase 0 — Foundation ✅ (2026-09-02)

New `apps/trust` app (registered in `LOCAL_APPS`). No behaviour change —
nothing reads any of this yet.

- **Providers** (`apps/trust/providers/`): abstract `SMSProvider`,
  `IDVerificationProvider`, `LivenessProvider`, `PhoneReachabilityProvider`,
  `PennyDropProvider`, `CaptchaProvider`, `ContentClassifierProvider` +
  `ProviderResult`. Dev adapters: `console` (SMS → log), `stub` (phone /
  CAPTCHA → deterministic pass, `FAIL_SENTINEL` forces fail), `manual` (ID /
  liveness / penny-drop → "needs a human"), `regex_classifier` (real
  contact-leakage detector: phone / UPI VPA / "pay me on GPay" / email / URL).
  Factory `get_provider(kind)` resolves the class from `TRUST_<KIND>_PROVIDER`.
- **Models** (`apps/trust/models.py`):
  - `TrustProfile` (OneToOne User) — `verification_score` 0–1,
    `is_fully_verified`, `risk_score` 0–100, `risk_state`
    (normal/limited/review/suspended), `lead_quality_score` 0–1, recompute
    stamps. 3 range CHECK constraints. Auto-created for every User via a
    `post_save` signal (`apps/trust/signals.py`), registered in `apps.py::ready`.
  - `ManualReviewItem` — the one queue all fraud/verification signals feed
    (`kind`, `status`, `priority`, `subject_user`, `summary`, `payload`,
    `dedupe_key`, assignee/resolution). `ManualReviewKind` covers teacher
    verification, duplicate account, fake lead, payment dispute, content flag,
    user report, reconciliation, anomaly, risk escalation.
- **`TrustService`** — `get_or_create_profile`, stub `recompute_verification_score`
  / `recompute_risk` (stamp only for now), `open_review_item` (dedupes on
  `(kind, dedupe_key)` while open), `resolve_review_item`.
- **Settings** (`config/settings/base.py`): 7 provider selectors + 15
  enforcement flags (all `False`) + 7 tunables. Pinned in `test.py`.
- **Admin**: `TrustProfile` + `ManualReviewItem` (read-mostly).
- Migration `apps/trust/0001_initial`. Also generated
  `student_requirement/0006_sync_class_duration_validators` — pre-existing
  metadata drift (help_text/validators only, no SQL), unrelated to this work.

**Tests:** `apps/trust/tests/test_providers.py` (10),
`apps/trust/tests/test_trust_profile.py` (6). Suite **283 → 299**, green.
`makemigrations --check` clean; `check --deploy` clean.

---

## Phase 1 — Email & Mobile OTP ✅ (2026-09-02)

Real OTP verification behind `User.is_email_verified` / `is_mobile_verified`.
Gates wired into the teacher paid/lead surfaces but **no-op while their flags
are OFF** (the default).

- **`OTPChallenge`** model — 6-digit, `sha256(code + SECRET_KEY)` at rest,
  10-min TTL, 5-attempt cap, single-use; a reissue supersedes the prior
  pending code. Migration `trust/0002`.
- **`OTPService`** (`apps/trust/services/otp_service.py`): `issue(user, channel)`
  → email via `send_mail` (console backend in dev) or SMS via the `sms`
  provider (console adapter logs the code); `verify(user, channel, code)` →
  flips the verified flag + `TrustService.recompute_verification_score`.
- **Endpoints** (`/api/v1/verify/`, new `apps/trust/urls.py`, mounted in
  `config/urls.py`): `status/`, `email/request/`, `email/confirm/`,
  `mobile/request/`, `mobile/confirm/`. Granted to every authenticated role in
  `apps/accounts/api_permissions.py`.
- **Throttle**: `OTPRequestThrottle` (scope `otp_request`, `6/hour` per
  (user, channel)) in `apps/core/throttling.py`; nulled in `test.py`.
- **Gates** (`apps/trust/gates.py`): `RequireVerifiedEmail` /
  `RequireVerifiedMobile` DRF permissions — return `True` unless
  `TRUST_REQUIRE_EMAIL_VERIFICATION` / `TRUST_REQUIRE_MOBILE_VERIFICATION` is
  ON. `default_permissions_with(*gates)` helper. Wired onto `UnlockLeadView`
  (`apps/lead_engine/views.py`) and `CreateOrderView` (`apps/payments/views.py`).
  *(Student-requirement gating deferred to Phase 6a, which has its own flag.)*
- **Web**: "Verify contact details" card in `templates/web/settings.html` —
  request + confirm codes per channel via Alpine, reads `/verify/status/`.

**Tests:** `apps/trust/tests/test_otp.py` (12) — issue/confirm/expire/attempt-cap/
reissue/throttle/status + gate OFF-noop / ON-blocks / ON-passes-verified.
Suite **299 → 311**, green. Live smoke: email + mobile OTP verified end-to-end
for student & teacher; teacher journey unchanged (unlock 200, no 403).

---

## Phase 2 — Step-up re-verification on sensitive changes ✅ (2026-09-02)

New self-service **change-email / change-mobile** flows, plus optional step-up
on password change. All two-step: initiate (validate + send a one-time code)
→ confirm (check the code).

- **`SensitiveChangeRequest`** model (`apps/trust`) — `field` (email/mobile/
  password), `new_value` (email/mobile) / `new_secret_hash` (password), FK to
  the `OTPChallenge`, `state` (awaiting_otp → scheduled → applied / cancelled /
  expired), `apply_after`. Migration `trust/0003` (+ new
  `OTPPurpose.SENSITIVE_CHANGE`).
- **`OTPService`** generalised — `issue(user, channel, purpose=, destination=)`
  and a `verify_challenge(challenge, code)` primitive so a specific pending
  challenge can be checked (Phase 1's `verify` now delegates to it).
- **`SensitiveChangeService`** (`apps/trust/services/sensitive_change_service.py`):
  - `initiate_email_change` / `initiate_mobile_change` — validate + dedupe-check
    + send the code to the **new** contact; notify the **current** email.
  - `initiate_password_change` — code to a **current verified** contact.
  - `confirm` — verifies the code. **Password** and **email/mobile with the flag
    OFF** apply immediately. **Email/mobile with `TRUST_ENABLE_STEP_UP_REVERIFICATION`
    ON** → `SCHEDULED`, `apply_after = now + TRUST_SENSITIVE_CHANGE_COOLDOWN_MINUTES`
    (default 60), owner notified with a cancel pointer.
  - `cancel`, `apply_due`, `expire_stale`. Every step writes a SECURITY audit row.
- **Celery beat** — `apps.trust.tasks.apply_due_sensitive_changes` every 60 s
  (applies elapsed cooldowns, expires unconfirmed requests). Idempotent.
- **Endpoints** (`apps/accounts`, `/api/v1/auth/`): `change-email/` + `.../confirm/`,
  `change-mobile/` + `.../confirm/`, `change-password/confirm/`, `sensitive-changes/`
  (list), `sensitive-changes/{id}/cancel/`. `ChangePasswordView` unchanged when
  the flag is OFF; two-step when ON. RBAC grants + `@extend_schema` on all.
- **Web** — "Change email or mobile" card in `templates/web/settings.html`.

**Tests:** `apps/trust/tests/test_sensitive_change.py` (13) — immediate path,
wrong-password, duplicate → 409, same-value → 400, step-up scheduled + cooldown
+ `apply_due`, owner cancel, list, password one-step-vs-two-step, expire_stale.
Suite **311 → 324**, green. `makemigrations --check` / `check --deploy` clean.
Live: change-email + change-password (step-up OFF) end-to-end for a student;
teacher & admin journeys unchanged (change-password 200).

---

## Phase 3 — Conditional CAPTCHA ✅ (2026-09-02)

A CAPTCHA challenge that only a suspected bot/account-farm client ever sees.
No models, no migration — entirely cache-backed.

- **`apps/trust/fingerprint.py`** — `client_fingerprint(request)` = sha256 of
  UA + Accept-* headers + optional `X-Device-Id` + IP (32 hex). Deliberately
  coarse; documented. Shared with Phase 4 dedup.
- **`CaptchaService`** (`apps/trust/services/captcha_service.py`):
  - `record_account_use(request, user_id)` — after every successful login /
    register / admin-login; keeps a per-fingerprint **rolling-24h set** of
    distinct user ids in the cache (sliding window, capped at 60).
  - `challenge_required(request)` — `True` only when `TRUST_ENABLE_CAPTCHA` is
    ON **and** the set size ≥ `TRUST_CAPTCHA_SWITCH_THRESHOLD` (default 10).
  - `verify_or_raise(request)` — no-op unless required; otherwise verifies the
    body's `captcha_token` via the `captcha` provider (stub adapter in dev:
    any non-empty token except the fail-sentinel passes) and raises
    `CaptchaRequiredException` (`error_code = "CAPTCHA_REQUIRED"`, 400) on
    failure. **Cache errors fail open** — a hiccup never blocks a login.
- **Wired** at the top of `LoginView.post`, `RegisterView.post`,
  `AdminLoginView.post` (`verify_or_raise`), with `record_account_use` on
  success.
- **Web** — `static/js/api.js` `friendly()` maps `CAPTCHA_REQUIRED` to a clear
  message. (A real reCAPTCHA/Turnstile widget is a going-live task: add the
  provider adapter + site-key script.)

**Tests:** `apps/trust/tests/test_captcha.py` (9) — distinct-user accumulation,
flag OFF never challenges, threshold boundary, `verify_or_raise` token
handling, cache-fail-open, + live-style login/register integration
(challenged at threshold, valid token clears it, fail-sentinel rejected).
Suite **324 → 333**, green. `check --deploy` clean. Live smoke (flag ON,
threshold 2): 3rd distinct login → `CAPTCHA_REQUIRED`, `captcha_token=solved`
→ 200. Flag OFF (default): all 4 role journeys + security checks unchanged.

---

## Phase 4 — Duplicate-account detection ✅ (2026-09-02)

Spots two accounts that are really the same person, even when
`User.email` / `User.mobile` uniqueness misses it (phone written
differently, Gmail dots/plus, same device).

- **Models** (`apps/trust`, migration `0004`):
  - `IdentitySignature` — `(user, kind, value_hash)` unique. `kind` ∈
    phone / email / device (+ `id_number` / `selfie_hash` reserved for
    Phase 5). `value_hash = sha256(kind:normalised:SECRET_KEY)`.
  - `DuplicateSignal` — a recorded collision `(user, matched_user, kind)`
    unique; links to a `ManualReviewItem`; `resolved` flag.
- **`DedupeService`** (`apps/trust/services/dedupe_service.py`):
  - `normalize_phone` (digits only, drop leading 0s, last 10),
    `normalize_email` (Gmail → strip dots + `+tag`, `googlemail`→`gmail`).
  - `record_signature(user, kind, raw_value)` — get-or-create the hashed sig.
  - `scan(user)` — compare the user's sigs to everyone else's; new
    collisions → `DuplicateSignal`s + **one** `ManualReviewItem`
    (`DUPLICATE_ACCOUNT`, deduped on `dupe:<user_id>`) + `recompute_risk`.
    Idempotent.
  - `record_and_scan_on_register` (phone + email + device) hooked into
    `RegisterView`; `record_and_scan_device` (device only, scans just when
    the device sig is new) hooked into `LoginView`. Both wrapped in
    `_safe_dedupe` — a failure never breaks auth.
  - `is_blocked(user)` — `True` only when `TRUST_ENABLE_DEDUP_BLOCKING` is
    ON and the user has an unresolved `DuplicateSignal`.
- **Gate** `NotFlaggedAsDuplicate` (`apps/trust/gates.py`) added to
  `UnlockLeadView` + `CreateOrderView` — no-op unless the flag is ON.
- **Resolution** — `TrustService.resolve_review_item` now also clears the
  linked `DuplicateSignal`s for a `DUPLICATE_ACCOUNT` item, unblocking the
  account.

**Tests:** `apps/trust/tests/test_dedupe.py` (13) — phone/email
normalisation, shared-phone + device collisions open a signal + review
item, no-collision no-signal, `scan` idempotent, blocking OFF-default /
ON, resolve-unblocks, gate OFF-noop / ON-blocks-flagged / ON-allows-clean,
register-integration. Suite **333 → 346**, green. `check --deploy` clean.
Flag OFF (default): all 4 role journeys unchanged.

---

## Phase 5 — Teacher verification progress bar + lead-probability scaling ✅ (2026-09-02)

The checklist that turns "manually flip verification_status" into an
automatic, scaled trust signal. **Both new matching behaviours are
feature-flagged and default OFF — the lead pipeline and search are
byte-for-byte unchanged until a flag is switched on.**

### 5a — checklist model + score
- `TeacherVerificationItem` (`apps/trust`, migration `0005`) —
  `(teacher, key)` unique, 10 keys. **Floor** (auto-derived, weight 60):
  `profile_basics` 15, `subjects_set` 10, `availability_set` 10,
  `email_verified` 10, `mobile_verified` 15. **Reviewed** (weight 40):
  `gov_id` 20, `selfie_liveness` 10, `address_proof` 5, `video_interview`
  5. `bank_penny_drop` seeded weight 0 (future payouts).
- `VerificationService` (`apps/trust/services/verification_service.py`):
  `ensure_items` (lazy row creation), `recompute` (refresh auto items →
  `verification_score` = verified weight / total = 0.000–1.000 on
  `TrustProfile`; score 1.0 → `is_fully_verified`; floor met → PENDING
  marketplace `verification_status` auto-upgraded to VERIFIED, **never
  downgraded** — admin verdicts stand), `snapshot` (API payload),
  `set_reviewed_item` / `submit_reviewed_item` (route to the id / liveness
  provider; manual adapter → SUBMITTED + a `TEACHER_VERIFICATION`
  review-queue item), `floor_predicate_q` (the queryset floor).

### 5b — recompute triggers
- `TrustService.recompute_verification_score` now delegates to
  `VerificationService.recompute` for teachers (so an OTP email/mobile
  verify immediately moves the bar).
- `apps.trust.tasks.recompute_teacher_verification_scores` — 6-hourly
  safety-net sweep (idempotent). Management command
  `recompute_verification_scores` — run before flipping the flags.

### 5c — endpoints
- Teacher: `GET /api/v1/teachers/profile/verification/` (snapshot),
  `POST /api/v1/teachers/profile/verification/{key}/submit/`.
- Admin: `POST /api/v1/admin/teacher-profiles/{id}/verification-items/{key}/`
  `{status, notes}` — verify / reject one item; resolves any linked
  review-queue item; audit-logged. RBAC grants added.

### 5d — matching (flag-gated)
- **Floor** — new `apps/trust/matching_support.py::apply_teacher_gate(qs)`
  replaces `.filter(verification_status=VERIFIED)` at all four candidate
  sites (`lead_distribution_service`, `lead_generation_service`,
  `search/views.py`, `matching/views.py`). OFF → exactly that filter. ON
  (`TRUST_TEACHER_FLOOR_FOR_LEADS`) → the auto-floor predicate (verified
  email + mobile + completed basic profile), minus admin-REJECTED.
- **Ranking bias** — `-verification_score` folded into the sort keys of
  `LeadDistributionService._group_by_tier` (within a tier, after
  subscription; tier still gates the cascade),
  `RankingService.rank_candidates`, `TeacherRankingService.sort_key`, and
  the search `DEFAULT_ORDER`, only when
  `TRUST_VERIFICATION_SCORE_AFFECTS_RANKING` is ON. Scores fetched in one
  query (`verification_score_map`). OFF → 0 for everyone → no reorder.

### 5e — web
- Verification card (progress meter + checklist + submit inputs) on
  `templates/web/teacher/profile.html`.
- "Fully verified" badge on `_teacher_card.html` + `student/teacher_detail.html`;
  `is_fully_verified` added to `TeacherProfileSerializer`
  (`teacher__user__trust_profile` select_related, guarded getattr).

**Tests:** `test_verification_score.py` (9), `test_verification_triggers.py`
(3), `test_verification_api.py` (8), `test_verification_matching.py` (8) —
score math, floor auto-upgrade, badge, admin never-downgrade, recompute
triggers, endpoint RBAC, and the flag matrix (floor ON/OFF eligibility,
ranking ON/OFF ordering). The existing `test_lead_pipeline.py` /
`test_teacher_search_ordering.py` / `test_verification.py` all stay green
unchanged (flags OFF). Suite **346 → 374**, green. `check --deploy` clean.
Live: checklist 60 % → submit gov_id → admin verify → 80 %; all 4 role
journeys unchanged.

> Note: a `black` run was accidentally scoped to whole app directories and
> reformatted ~58 pre-existing files in `lead_engine` / `matching` /
> `teacher_profile` / `search` (formatting only — semantics unchanged, full
> suite + `makemigrations --check` green). Future formatting is scoped to
> named files only.

---

## Phase 6 — Student verification & lead-quality feedback ✅ (2026-09-02)

Student-side identity assurance + a teacher-driven feedback loop that
refunds tokens spent on fake / unreachable leads and risk-flags the
student behind them. **Every gate is flag-gated, default OFF** — the
requirement-post flow, the unlock flow, and lead distribution are
byte-for-byte unchanged until a flag is switched on.

### 6a — student verified-to-post gate
- `RequireVerifiedToPostRequirement` (`apps/trust/gates.py`) on
  `StudentRequirementListCreateView`. SAFE methods always pass. When
  `TRUST_REQUIRE_STUDENT_VERIFIED_TO_POST` is ON, a POST needs
  `is_email_verified and is_mobile_verified` → else 403. OFF → no-op.

### 6b — phone reachability before a teacher is charged
- Models (`apps/trust`, migration `0006`): `RequirementContactCheck`
  (OneToOne `StudentRequirement`, `reachable`, cached — one provider call
  per requirement, survives rollback).
- `ReachabilityService` (`apps/trust/services/reachability_service.py`):
  `check_requirement` (calls the `phone_reachability` provider — stub
  passes in dev, empty / `FAIL_SENTINEL` number fails), `block_if_unreachable`
  → on failure adds a `PHONE_UNREACHABLE` `RiskSignal` and raises
  `LeadContactUnreachable` (409, `LEAD_CONTACT_UNREACHABLE`).
- `unlock_lead_contact` split: the reachability gate runs **before** the
  charging transaction (`_unlock_lead_contact_txn`), so an unreachable
  student never costs a free lead or a token and the signal/flag rows are
  not rolled back. No-op unless `TRUST_ENABLE_PHONE_REACHABILITY_CHECK`.

### 6c — requirement velocity + shadow-limit
- `RequirementVelocityService` (`apps/trust/services/requirement_velocity_service.py`):
  - `guard(student)` — ≥ `TRUST_REQUIREMENT_MAX_PER_DAY` (default 10) in 24h
    or ≥ `TRUST_REQUIREMENT_MAX_OPEN` (default 15) open → `ThrottledException`
    (429).
  - `note_abandonment(student)` — **flag-gated** (no-op when the flag is off,
    since it runs off every requirement POST). Counts only *closed / expired*
    requirements; once ≥ 5 of them and the productive ratio (leads actually
    contact-unlocked) < 20% → a weight-25 `REQUIREMENT_ABANDONMENT`
    `RiskSignal`. Open-requirement hoarding is left to `guard`'s max-open cap.
  - `should_hold(student)` — `True` when the student is shadow-limited
    (`risk_state` ≥ limited).
- `StudentRequirementListCreateView.create` calls `guard` before the
  serializer; a shadow-limited student's requirement is saved with the new
  `LeadDistributionStatus.HELD` (migration `student_requirement/0007`,
  choices-only) and distribution is replaced by a
  `ManualReviewItem`. `note_abandonment` runs post-commit (best-effort).
  All no-ops unless `TRUST_ENABLE_REQUIREMENT_VELOCITY`.

### 6d — lead-quality feedback + token clawback
- Models (`apps/trust`, migration `0006`):
  - `RiskSignal` — `(user, kind, weight, active, expires_at, payload)`;
    kinds cover velocity / abandonment / lead-quality / phone-unreachable /
    duplicate / payment / anomaly. Deduped per active `(user, kind)`.
  - `LeadQualityRating` — `(teacher, lead)` unique, `verdict`
    genuine / unreachable / fake, `clawed_back`.
- `RiskService` (`apps/trust/services/risk_service.py`): `add_signal`
  (dedupe + recompute), `recompute` (Σ active weights, capped 100 →
  `risk_score`; thresholds 20 / 50 / 80 → limited / review / suspended),
  `is_shadow_limited`. `TrustService.recompute_risk` now delegates here.
- `LeadQualityService` (`apps/trust/services/lead_quality_service.py`):
  `rate(teacher, lead, verdict, note)` — requires a real
  `LeadUnlockHistory` row, `update_or_create`s the rating, then `_reassess`
  the student: `lead_quality_score` = genuine / total; once ≥
  `TRUST_LEAD_QUALITY_CORROBORATION` (default 2) **distinct** teachers rate
  a student's leads bad → a weight-45 `LEAD_QUALITY` `RiskSignal` + a
  priority-2 review item, and (only if `TRUST_ENABLE_LEAD_QUALITY_CLAWBACK`)
  `WalletService.refund` each corroborating teacher's paid unlock cost,
  marking the rating `clawed_back`. Free unlocks are never refunded.
- Endpoint `POST /api/v1/leads/{id}/rate/` (`LeadRateView`, granted to
  `_TEACHER`); invalid verdict → 400. Web: a "Rate this lead" card
  (genuine / unreachable / fake + optional note) on
  `templates/web/teacher/lead_detail.html`, shown once the contact is
  unlocked.

**Settings:** flags `TRUST_REQUIRE_STUDENT_VERIFIED_TO_POST`,
`TRUST_ENABLE_PHONE_REACHABILITY_CHECK`, `TRUST_ENABLE_REQUIREMENT_VELOCITY`,
`TRUST_ENABLE_LEAD_QUALITY_CLAWBACK` (all `False`, pinned in `test.py`);
tunables `TRUST_REQUIREMENT_MAX_PER_DAY` 10, `TRUST_REQUIREMENT_MAX_OPEN` 15,
`TRUST_LEAD_QUALITY_CORROBORATION` 2.

**Post-build hardening pass** (2026-09-02, after the phase's disconnects):
`note_abandonment` gated behind the flag + narrowed to terminal requirements
(was flagging students whose fresh requirements simply weren't worked yet);
`unlock_lead_contact` split so the reachability gate + its risk-signal /
contact-check writes run *before* (and outside) the charging transaction —
they no longer roll back when the unlock aborts; `ReachabilityService`
`check_requirement` now `get_or_create` (concurrent unlocks of the same
requirement no longer race to a 500 on the OneToOne); `RiskService.add_signal`
truncates `detail` and no longer clobbers a time-boxed signal's expiry on a
plain re-fire; `LeadRateView` coerces `verdict`/`note` to `str` (malformed
body → 400 not 500); the held-requirement review-item open is wrapped so a
failure can't 500 the POST. Suite **391 → 394**.

**Tests:** `apps/trust/tests/test_phase6.py` (20) — gate OFF-noop /
ON-blocks-unverified / ON-allows-verified; reachability OFF-noop,
reachable unlocks, unreachable + sentinel block without charging (+ risk
signal, no `LeadUnlockHistory`, wallet untouched), `check_requirement`
idempotent; velocity 429 at the cap + OFF-noop, shadow-limited → HELD,
abandonment signal (terminal-only) + ignores-open + OFF-noop; rating needs
an unlock, single fake → score 0, corroborated clawback refunds both paid
teachers once + signal, corroboration-without-flag still signals but no
refund; endpoint 200 + student-cannot-rate 403. Suite **374 → 394**,
green. `makemigrations --check` / `check --deploy` clean. Live smoke:
teacher registers → verified → gets a lead → unlock 200 → rate genuine
200, bad verdict 400. Flags OFF (default): student + teacher live
journeys unchanged, no latency change, zero 5xx.

---

## Phase 7 — Payment & transaction fraud ✅ (2026-09-02)

Hardens the money path: server-verified amounts, idempotent crediting,
payment-fraud signals, chargeback token freezes, refund-abuse detection,
daily ledger reconciliation, and a new-account purchase cooldown.
Migrations: `payments/0004`–`0006`, `wallet/0002`, `trust/0007` (choices).

### 7a / 7b — amount check + idempotency  *(always on — pure correctness)*
- `apps/payments/services.py` restructured: `_mark_payment_successful` now
  runs a **server-side amount gate first, outside** the crediting
  transaction. `verify_payment` calls `client.payment.fetch()` (skipped
  when Razorpay isn't configured) and the webhook reads
  `payload.payment.entity.amount`; either captured-amount ≠ order amount →
  `PaymentAmountMismatch` (400), Payment marked FAILED on its own commit,
  `PAYMENT_RISK` `RiskSignal` + SECURITY audit, wallet never touched.
- `_credit_successful_payment` re-loads the Payment `select_for_update(of=("self",))`
  and re-checks `status == SUCCESS`, so verify + webhook (or webhook
  retries) racing the same payment credit the wallet exactly once.
- Webhook dedupe on `razorpay_event_id` was already solid; unchanged.

### 7c — payment-risk signals  *(flag `TRUST_ENABLE_PAYMENT_RISK_CHECKS`)*
- `PaymentInstrumentSignature` model — hashed UPI VPA / card token / wallet
  handle per teacher (`(teacher, kind, value_hash)` unique). Never stores
  the raw value.
- `apps/payments/risk.py` `PaymentRiskService` — from the webhook entity:
  one instrument across ≥ `TRUST_PAYMENT_INSTRUMENT_MAX_ACCOUNTS` (3)
  distinct teachers → `PAYMENT_RISK` signal + `PAYMENT_RISK` review item
  (deduped on the instrument hash); a purchase > `TRUST_PAYMENT_SPIKE_MULTIPLIER`
  (5)× the teacher's prior max → spike signal; `TRUST_PAYMENT_FAILED_BURST`
  (5) failed attempts/hour (cache counter, also fed by `verify_payment`
  signature failures) → burst signal. All no-ops with the flag off.

### 7d — disputes + wallet holds
- `WalletHold` (`apps/wallet`) — freezes part of a balance without moving
  the `balance` figure. `WalletService`: `available_balance` = balance −
  Σ active holds; `debit` / `has_sufficient_balance` now enforce
  *spendable* balance (held tokens can't be spent on unlocks);
  `place_hold` (clamped to current balance), `release_hold`,
  `settle_hold_as_debit`.
- `PaymentDispute` (`apps/payments`) — `kind` chargeback/refund,
  `external_ref` unique (dedupes webhook retries), `status`,
  `wallet_hold`, `review_item`. `apps/payments/disputes.py` `DisputeService`
  handles `payment.dispute.created/won/lost/closed` and
  `refund.created/processed`: records the dispute + priority-1
  `PAYMENT_DISPUTE` review item + SECURITY audit **always**; freezes the
  proportional tokens via a `WalletHold` **only when
  `TRUST_ENABLE_PAYMENT_RISK_CHECKS` is on**. Resolution: won → release
  hold; lost → settle as a debit (claw back).

### 7e — refund abuse  *(`apps/payments/refunds.py`, always on)*
- `RefundEligibilityService.assess` / `flag_if_abusive` — token balances
  are fungible, so a payment's tokens are refundable only up to the
  wallet's spendable balance; a refund/chargeback covering already-spent
  tokens raises a weight-40 `PAYMENT_RISK` signal + priority-1 review item.
  Called from `DisputeService.open` before the hold.

### 7f — daily reconciliation
- `ReconciliationRun` model + `apps/payments/reconciliation.py`
  `ReconciliationService.run(window)` — every SUCCESS token-purchase
  Payment must have a matching CREDIT `WalletTransaction` (same
  `reference_id`, same token count); no CREDIT may reference a non-SUCCESS
  payment; when Razorpay is configured, each is confirmed "captured" +
  amount-matched against the gateway. Drift → `RECONCILIATION` review item
  + SECURITY audit. `@shared_task reconcile_payments` (beat: daily) +
  `manage.py reconcile_payments [--days N]`.

### 7g — new-account cooldown  *(flag `TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN`)*
- `apps/payments/cooldown.py` `NewAccountCooldownService` — for the first
  `TRUST_NEW_ACCOUNT_COOLDOWN_HOURS` (24) after signup: `guard_order_amount`
  rejects a single order over `TRUST_NEW_ACCOUNT_MAX_PURCHASE` (2000) with
  `PaymentHeldForReview` (409); `maybe_hold_new_tokens` freezes tokens
  bought in that window via a `WalletHold`. `@shared_task
  release_due_cooldown_holds` (beat: hourly) lifts holds once the window
  elapses.

**Settings:** flags `TRUST_ENABLE_PAYMENT_RISK_CHECKS`,
`TRUST_ENABLE_NEW_ACCOUNT_COOLDOWN` (both `False`, pinned in `test.py`);
tunables `TRUST_PAYMENT_INSTRUMENT_MAX_ACCOUNTS` 3, `TRUST_PAYMENT_FAILED_BURST`
5, `TRUST_PAYMENT_SPIKE_MULTIPLIER` 5, `TRUST_NEW_ACCOUNT_COOLDOWN_HOURS` 24,
`TRUST_NEW_ACCOUNT_MAX_PURCHASE` 2000. New beat tasks: `reconcile-payments`
(daily), `release-cooldown-holds` (hourly).

**Tests:** `test_payment_fraud.py` (13), `test_disputes.py` (16),
`test_reconciliation.py` (5), `test_cooldown.py` (9). Suite **394 → 435**,
green. `makemigrations --check` / `check --deploy` clean. Live smoke
(flags OFF): amount-mismatch webhook → 200 + FAILED + no credit + risk
signal; correct-amount webhook → SUCCESS + credited; dispute webhook →
recorded, 0 tokens frozen (freeze gated). Teacher + student journeys
unchanged, zero 5xx.

---

## Phase 8 — Off-platform leakage, content moderation, reviews ✅ (2026-09-02)

Content scanning + profile moderation, a review system with integrity
rules, and report/block. New app **`apps/reviews`**. Migrations:
`trust/0008` (ContentFlag, UserReport, UserBlock, RiskSignalKind choices),
`teacher_profile/0005` (moderation_status), `reviews/0001`.

### 8a / 8b — content scan + profile moderation  *(flag `TRUST_ENABLE_CONTACT_LEAKAGE_SCAN`)*
- `apps/trust/services/content_scan_service.py` `ContentScanService` runs
  the `content_classifier` provider (regex: phone / UPI VPA / gpay-phonepe-paytm
  phrasing / email / URL) over `TeacherProfile.headline`, `Teacher.bio`,
  `Teacher.qualification_detail`, and (8c) review text.
- `ContentFlag` model — one hit per surface, links a `CONTENT_FLAG` review
  item. `TeacherProfile.moderation_status` (`clear` / `held`).
- Hooked into both profile save paths (`apps/teachers` + `apps/teacher_profile`
  views): a hit → `moderation_status = HELD` + review item + weight-25
  `CONTENT_LEAKAGE` risk signal. A later **clean** edit self-heals
  (resolves the flags, restores `CLEAR`). Admin actions on
  `TeacherProfileAdmin`: clear / hold.
- `matching_support.apply_teacher_gate` now also `.exclude(moderation_status=HELD)`
  when the flag is on → held profiles vanish from search + all 4 lead
  candidate sites, but stay fully visible to the teacher (web banner on
  `teacher/profile.html`). OFF → byte-for-byte unchanged.

### 8c — reviews  *(flag `TRUST_ENABLE_REVIEW_SYSTEM`, new `apps/reviews`)*
- `Review` model (author, teacher, `source_lead`, rating 1–5, text,
  `status`, `author_fingerprint`); unique `(author, source_lead)`.
- `ReviewIntegrityService`: requires a real prior link (a
  `LeadUnlockHistory` **or** accepted `LeadAssignment` connecting author↔teacher);
  rejects self-review and duplicate-per-lead; runs the content scan on the
  text (hit → `FLAGGED`, not `PUBLISHED`); rating-ring detection (≥3 reviews
  from one `author_fingerprint` / ≥5 five-star for one teacher in 24h →
  `FLAGGED` + review item). `recompute_teacher_rating` sets
  `TeacherProfile.rating` = avg of **PUBLISHED** reviews (no-op while the
  flag is off, so the field stays admin-managed).
- Endpoints: `GET/POST /api/v1/reviews/` (student), `DELETE /api/v1/reviews/{id}/`,
  `GET /api/v1/teachers/{id}/reviews/`. All 404 while the flag is off. Web:
  reviews card on `student/teacher_detail.html`.

### 8d — report & block
- `UserReport` (reporter, reported, reason, → `USER_REPORT` review item +
  weight-20 `USER_REPORT` risk signal + audit; deduped per open pair) and
  `UserBlock` (`(blocker, blocked)` unique). Endpoints at `/api/v1/safety/`:
  `report/`, `blocks/` (GET/POST), `blocks/{user_id}/` (DELETE). Report +
  block CRUD are **always on** (build the list before flipping the switch).
- `matching_support.exclude_blocked_teachers(qs, viewer)` filters both
  directions of a block out of search + lead distribution + lead
  generation — no-op unless the new flag `TRUST_ENABLE_USER_BLOCKING` is on.

**Settings:** flags `TRUST_ENABLE_CONTACT_LEAKAGE_SCAN`,
`TRUST_ENABLE_REVIEW_SYSTEM`, `TRUST_ENABLE_USER_BLOCKING` (all `False`,
pinned in `test.py`). `apps.reviews` added to `LOCAL_APPS`.

**Tests:** `apps/trust/tests/test_content_scan.py` (8),
`apps/reviews/tests/test_reviews.py` (12),
`apps/trust/tests/test_report_block.py` (8). Suite **435 → 463**, green.
`makemigrations --check` / `check --deploy` clean. Live smoke (flags OFF):
leaky headline → saved, `moderation_status=clear` (no hold); `/reviews/` →
404; `/safety/report/` + `/safety/blocks/` → 201, list shows the block.
Teacher + student journeys unchanged, zero 5xx.

---

## Phase 9 — Risk scoring, anomaly alerts, ops consolidation ✅ (2026-09-02)

Consolidates every fraud/verification signal into one risk score with
optional auto-enforcement, adds login anomaly detection, and gives ops a
single review queue. Migration: `trust/0009` (`TrustProfile.known_countries`).

### 9a — risk engine + auto-actions  *(flag `TRUST_ENABLE_RISK_AUTO_ACTIONS`)*
- `DedupeService.scan` now also raises a weight-30 `DUPLICATE_ACCOUNT`
  `RiskSignal` (previously it only opened a review item), so duplicate
  accounts actually move the score.
- `RiskService.recompute` opens/resolves a **`RISK_ESCALATION`** review
  item (deduped `risk:{user_id}`) as a user crosses the `review` line —
  **always**, so ops sees it even with auto-actions off.
- `RiskService.is_suspended(user)` — True only when auto-actions are on
  AND `risk_state == suspended`. New gate `NotRiskSuspended`
  (`apps/trust/gates.py`) wired onto `UnlockLeadView`, `CreateOrderView`,
  `StudentRequirementListCreateView`, and `ReviewIntegrityService.create_review`.
- `RiskService.ranking_penalty` + `matching_support.risk_penalty_map` fold a
  bounded down-rank (limited 1 / review 2 / suspended 3) into
  `TeacherRankingService.sort_key` — `{}` (no-op) unless auto-actions on.
- `@shared_task recompute_risk_scores` (beat: every 6h) — decays expired
  signals + keeps `risk_state` + the escalation item accurate for every
  user with a signal.

### 9b — anomaly alerts  *(flag `TRUST_ENABLE_ANOMALY_ALERTS`)*
- `GeoIPProvider` abstract + `StubGeoIPProvider` (`203.* → SG`, `8.8./1.1.* → US`,
  else `IN`); selector `TRUST_GEOIP_PROVIDER=stub`.
- `AnomalyService.on_login(user, request)` — runs in `LoginView` before the
  dedupe device write: login from a country not in `TrustProfile.known_countries`,
  login from a device the account has never used, or ≥
  `TRUST_ANOMALY_ACCOUNTS_PER_DEVICE` (4) accounts on one device fingerprint
  in 24h → each records a weight-15 `ANOMALY` `RiskSignal` + one `ANOMALY`
  review item (deduped `anomaly:{user_id}`) + SECURITY audit.
- `AnomalyService.note_refund(user)` (called from `DisputeService.open`) — 3
  refunds/disputes for one user in 24h → anomaly.

### 9c — ops review queue
- `apps/ops` (Super-Admin only, like the rest of ops):
  `GET /api/v1/ops/review-queue/` (filter by kind / status / priority /
  `assignee=me` / search; returns `open_by_kind` counts),
  `POST .../review-queue/{id}/resolve/` (`{dismiss, resolution}` →
  `TrustService.resolve_review_item` + audit),
  `POST .../review-queue/{id}/assign/` (to self → `IN_REVIEW`),
  `GET /api/v1/ops/risk/` (TrustProfiles by `risk_state` + counts).
- Web: `super-admin/review-queue/` page + "Review queue" nav link. The
  teacher-verification queue item already flows through here (same
  `ManualReviewItem` table).

### 9d — evidence retention
- `VerificationService.set_reviewed_item` now writes a SECURITY audit row
  (`verification_evidence_submitted` / `_reviewed`) on every evidence
  attach / verdict — records the *reference*, never document content.
  Webhook payloads were already retained (`PaymentWebhook`). Retention
  windows documented below.

**Settings:** flags `TRUST_ENABLE_ANOMALY_ALERTS`, `TRUST_ENABLE_RISK_AUTO_ACTIONS`
(both `False`, pinned in `test.py`); provider `TRUST_GEOIP_PROVIDER=stub`;
tunable `TRUST_ANOMALY_ACCOUNTS_PER_DEVICE` 4. New beat task
`recompute-risk-scores` (6h).

**Tests:** `apps/trust/tests/test_phase9.py` (12) — threshold transitions,
escalation item open/resolve, `is_suspended` flag+state gating, dedupe risk
signal, suspended student → 403 (+ OFF no-op), anomaly OFF no-op / new
country / refund spike, review-queue list+assign+resolve, queue
Super-Admin-only, `/ops/risk/`. Suite **463 → 475**, green.
`makemigrations --check` / `check --deploy` clean. Live smoke: superadmin
`/ops/review-queue/` + `/ops/risk/` → 200 (risk counts populated by earlier
test data); student → 403. Teacher + student journeys unchanged, zero 5xx.

---

## Phase 10 — Full verification & docs ✅ (2026-09-02)

Final phase: no new features — prove the whole stack holds together under
enforcement, and write the operator docs (sections 1–5 + the retention
table at the top/bottom of this file).

- **All-flags-ON integration suite** — `apps/trust/tests/test_phase10_integration.py`
  (9 tests, `@override_settings` with all 18 flags true at once):
  - *Student gauntlet*: unverified → 403, verified → 202; risk-limited →
    requirement `HELD`; risk-suspended → 403; a blocked teacher is absent
    from that student's candidate leads.
  - *Teacher gauntlet*: below the Phase-5 floor → no leads; onboarded +
    verified → gets leads; unlock blocked+uncharged on an unreachable
    student, succeeds on a reachable one; a new-account ₹50k order → 409.
  - *Ops queue*: a content flag + a user report + a risk escalation all
    surface in `GET /ops/review-queue/` for Super-Admin, and resolve.
  - Note: `TRUST_CAPTCHA_SWITCH_THRESHOLD` is pushed to 100000 in the ON
    matrix because the test client's fingerprint is constant across the
    suite; real clients vary.
- **Live journeys** — flags OFF: student + teacher + admin scripts run
  clean (the one admin-journey 400 is the script re-`POST`ing a fixed
  `lead-unlock-pricing` tier, pre-existing, not a regression). Flags ON:
  the verified-to-post gate returns 403 for an unverified student on the
  real server; no 5xx.
- Suite **475 → 484**, green. `makemigrations --check` / `check --deploy`
  clean.

**Program totals:** 10 phases · `apps/trust` + `apps/reviews` + payment
fraud modules · 18 enforcement flags (all default OFF) · 8 pluggable
providers · 6 Celery beat tasks · suite **283 → 484**.

---

## Post-program review pass ✅ (2026-09-02)

A phase-by-phase re-read for broken code / workflow hindrances. Fixes
(suite **484 → 488**, all default-OFF behaviour unchanged):

- **P2** `SensitiveChangeService.apply_due` retried a failing `_apply` every
  60s forever (usual cause: the target email/mobile got taken during the
  cooldown). Now: `_apply` re-checks uniqueness and raises; `apply_due`
  marks the request `EXPIRED` + emails the owner instead of looping.
- **P5** the cached `verification_score` / "Fully verified" badge only
  refreshed on an OTP verify or the 6-hourly sweep — a teacher who just
  finished their profile saw a stale badge for hours. Added
  `recompute_for_user` hooks to the basic-details, marketplace-profile and
  weekly-availability save paths. (`floor_predicate_q` was already live, so
  lead eligibility was never stale.)
- **P5** `submit_reviewed_item` returned a misleading "Bank verification
  isn't available yet" for an unknown item key — now a clear 400.
- **P7** `process_webhook` read the dedup id from `payload["id"]`, which
  **real Razorpay webhooks don't send** — the id is the `X-Razorpay-Event-Id`
  header. In production every webhook would have collided on an empty id.
  Now: header first, body field, then a raw-body hash; the view passes the
  header and 200s (not 500s) on any unexpected error so Razorpay stops
  retrying.
- **P7** a payment confirmed by the capture webhook alone (client closed the
  browser before `verify`) kept `razorpay_payment_id` NULL, so a later
  dispute/refund webhook couldn't link it. Now the capture webhook persists
  the gateway payment id.
- **P7g** cooldown holds were released once the *hold* was `cooldown_hours`
  old, not once the *account* was — a purchase late in the window stayed
  frozen for up to a full extra window. Now keyed off account age.
- **P8c** `TeacherReviewsView.get` recomputed (and wrote) the rating on
  every read, zeroing a teacher's legacy/admin rating the moment their
  review page was opened with the flag on. Reads now use a non-writing
  `average_rating`; the stored rating only changes on an actual review
  create / delete / status change.
- **P8d** `DELETE /safety/blocks/{id}/` 404'd if the blocked user had since
  been deactivated — you couldn't unblock them. Now unblocks by id directly.

---

## Evidence retention

| Data | Store | Retention |
|---|---|---|
| Verification evidence *references* (`TeacherVerificationItem.evidence_ref`) | DB | Life of the account + 1 year; every attach/verdict audit-logged |
| Verification documents (when a real ID/liveness provider is wired) | Django storage under a per-teacher restricted prefix; access via a signed, short-TTL URL only | 90 days after a final verdict, then purged |
| Razorpay webhook payloads (`PaymentWebhook.payload`) | DB, append-only | 7 years (financial record) |
| `AuditLog` (all SECURITY / OPS actions) | DB, append-only | 3 years |
| `RiskSignal` / `ManualReviewItem` / `ContentFlag` | DB | 2 years after resolution |
| `IdentitySignature` (hashed, no raw PII) | DB | Life of the account |
