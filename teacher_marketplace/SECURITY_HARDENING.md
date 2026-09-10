# Security Hardening — Plan & Log

Started 2026-09-01. Goal: raise the platform's defence to a professional
"defence-in-depth" standard across every major attack class, **without**
changing any behaviour a Student / Teacher / Admin / Super-Admin sees, and
**without** adding measurable latency at scale.

> Honest scoping note: no system is "100% unhackable". What this work delivers
> is *defence in depth* — every realistic attack class (OWASP Top 10 + API Top
> 10 + infra) gets at least one, usually two, independent controls in front of
> it, so a single mistake never becomes a breach. All controls here are
> **middleware / settings / validation-layer** only. None touch business logic,
> none add a DB query on the hot path, none change a response body that a
> legitimate client relies on.

---

## Current posture (audit result — already strong)

| Area | Already in place |
|---|---|
| AuthN | SimpleJWT, Argon2id hashing, httpOnly cookie transport, single-active-session `sid` binding, refresh rotation + blacklist, access-token killed on logout |
| AuthZ | Centralised **default-deny** role→method→route registry (`RoleBasedAPIPermission`), Super-Admin approval flow for admin logins, impersonation is time-boxed + audited |
| Injection | ORM-only (no raw SQL), DRF `JSONParser`, `JSONRenderer` only, Django template autoescape, no `|safe` / `mark_safe` on user data, field validators reject control chars & `<>` |
| Transport | production forces HTTPS redirect, HSTS 1y + preload, secure cookies, `SameSite=Lax` |
| Error handling | Uniform `{success,error}` envelope, never leaks stack traces, generic 500 |
| Data integrity | 14 write-endpoint areas hardened with model validators + DB CHECK constraints (see `DATA_HARDENING.md`) |
| Abuse | DRF throttling (anon 100/h, user 1000/h), forgot-password does not reveal account existence |
| Payments | Razorpay webhook HMAC-verified, graceful 503 on gateway failure |
| Secrets | `python-decouple`, production fails loudly on missing env var, `DEBUG=False` enforced |

## Gaps this work closes

1. No `Content-Security-Policy` / `Permissions-Policy` header.
2. Security response headers (`nosniff`, `X-Frame-Options`, referrer policy) only applied in `production.py`, not `base.py`.
3. No dedicated brute-force throttle on `login` / `register` / `forgot-password` / `reset-password` / `admin-login` (only the broad anon bucket).
4. Throttle counters are per-process (LocMem) → at scale with N workers the effective limit is N×. Needs a shared cache option.
5. No request-body size / field-count ceiling tuned for a JSON API.
6. Profile-photo `ImageField` has no size / dimension / content-type ceiling.
7. Dependency pins are a few patch releases behind published CVE fixes.
8. `manage.py check --deploy` not part of CI / not clean.
9. No dedicated security regression test module.

---

## Task list (one at a time; full suite + role journeys after each)

| # | Task | Files | Risk |
|---|---|---|---|
| **S1** | Security response headers everywhere: CSP + Permissions-Policy middleware; move `nosniff` / `X-Frame-Options` / referrer / COOP to `base.py` | new `apps/core/middleware/security_headers.py`, `config/settings/base.py` | none (headers only) |
| **S2** | Brute-force throttle scopes on all auth endpoints (`login` 10/min, `register` 20/h, `password_reset` 5/h, `admin_login` 10/h) | new `apps/core/throttling.py`, `apps/accounts/views.py`, `apps/accounts/admin_api.py`, settings | none (limits are far above real use) |
| **S3** | Request-size & field-count ceilings for the JSON API | `config/settings/base.py` | none |
| **S4** | Profile-photo upload validator (≤ 5 MB, jpeg/png/webp, ≤ 5000 px) | `apps/utils/validators.py`, `apps/students/models.py`, `apps/teachers/models.py` + migration | low (rejects only oversized / non-image) |
| **S5** | Shared-cache throttling for scale — opt-in Redis cache backend | `config/settings/production.py` | none (falls back to LocMem if unset) |
| **S6** | Dependency CVE review + safe patch bumps | `requirements.txt` | medium — full suite gates each bump |
| **S7** | `manage.py check --deploy` → clean | settings | none |
| **S8** | Security regression test suite | new `apps/core/tests/test_security_headers.py`, `apps/accounts/tests/test_auth_throttling.py` | none (tests only) |
| **S9** | Live role journeys: Student → Teacher → Admin → Super-Admin, confirm zero delay / error | scratchpad scripts | verification only |

---

## Log

### S1 — Security response headers (DONE 2026-09-01)

- New `apps/core/middleware/security_headers.py::SecurityHeadersMiddleware`
  (2nd in `MIDDLEWARE`, right after `SecurityMiddleware`). Adds
  **Content-Security-Policy** and **Permissions-Policy** to every response
  (web + API + errors). Values cached on the instance at process start →
  per-response cost is one `in` check + one assignment, no I/O.
  - CSP: `default-src 'self'`; `object-src`/`frame-ancestors` none;
    `base-uri`/`form-action` self; `script-src` self + inline + eval
    (Alpine.js needs both) + `checkout.razorpay.com`; `connect-src` /
    `frame-src` self + Razorpay; `img-src` self+data+blob+Razorpay.
  - `CONTENT_SECURITY_POLICY` / `PERMISSIONS_POLICY` settings override the
    defaults; `CONTENT_SECURITY_POLICY_REPORT_ONLY=True` for trialling.
- `config/settings/base.py`: moved `SECURE_CONTENT_TYPE_NOSNIFF`,
  `X_FRAME_OPTIONS=DENY`, `SECURE_REFERRER_POLICY=strict-origin-when-cross-origin`,
  `SECURE_CROSS_ORIGIN_OPENER_POLICY=same-origin`, `SESSION_COOKIE_HTTPONLY`
  from `production.py` up to `base.py` so dev/staging get them too (all are
  browser-only directives — inert on plain-HTTP localhost).
- Verified live: headers present on `/login/` (web) and `/api/v1/subjects/`
  (API). Full suite **263 green**. No UI regression (all app JS/CSS is
  same-origin `{% static %}`; inline + eval allowed for Alpine).

### S2 — Brute-force / enumeration throttling (DONE 2026-09-01)

- New `apps/core/throttling.py`:
  - `LoginRateThrottle` — keys on **(client IP, sha256(email))**, so a shared
    IP (school lab / office NAT / carrier CGNAT) is throttled *per account*,
    never collectively. Scope `login` = `10/min`.
  - `RegisterRateThrottle` / `PasswordResetRateThrottle` / `AdminLoginRateThrottle`
    — per client IP. Scopes `register` `30/hour`, `password_reset` `10/hour`,
    `admin_login` `20/hour`.
  - All subclass `_ResilientScopedThrottle` → a cache-backend error **fails
    open** (allows the request) rather than 500-ing a login.
- Wired as `throttle_classes = [AnonRateThrottle, <scoped>]` on
  `RegisterView`, `LoginView`, `ForgotPasswordView`, `ResetPasswordView`
  (`apps/accounts/views.py`) and `AdminLoginView` (`apps/accounts/admin_api.py`).
  The global anon bucket stays as a second ceiling.
- Rates live in `config/settings/base.py` `DEFAULT_THROTTLE_RATES`; nulled in
  `config/settings/test.py` (tests re-enable per-scope).
- Over-limit → existing `THROTTLED` 429 envelope (no handler change needed).
- New `apps/accounts/tests/test_auth_throttling.py` (6 tests). Full suite
  **269 green**.

### S3 — Request-body / field-count ceilings (DONE 2026-09-01)

- `config/settings/base.py`: `DATA_UPLOAD_MAX_MEMORY_SIZE = 2 MB` (JSON
  bodies are a few KB; file fields are exempt and capped separately),
  `DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000` (hash-flood guard, still roomy for
  Django-admin bulk actions), `DATA_UPLOAD_MAX_NUMBER_FILES = 10`.
  Full suite **269 green**.

### S4 — Profile-photo upload validation (DONE 2026-09-01)

- New `apps.utils.validators.validate_image_upload`: <= 5 MB, <= 6000 px per
  side, JPEG/PNG/WebP only — **verified by decoding the image header with
  Pillow**, not by trusting the filename or client `Content-Type`. Rejects a
  disguised HTML/SVG/script payload, a decompression bomb, and storage abuse.
  Only runs when a *new* file is uploaded.
- Attached to `Student.profile_photo` + `Teacher.profile_photo` → propagated
  to the DRF `ImageField`. Migrations `students/0003`, `teachers/0004`
  (state-only). New `apps/students/tests/test_photo_upload_validation.py`
  (5 tests). Full suite **274 green**.

### S5 — Fail-open throttling + shared-cache option for scale (DONE 2026-09-01)

- `apps/core/throttling.py`: added `ResilientAnonRateThrottle` /
  `ResilientUserRateThrottle` (stock DRF behaviour + fail-open on cache
  error) and made them the project defaults (`DEFAULT_THROTTLE_CLASSES`).
  A Redis/cache outage now degrades to "limits briefly not enforced",
  never to a 500 on every request.
- `config/settings/production.py`: opt-in `REDIS_CACHE_URL` → default cache
  becomes `RedisCache` (0.2 s socket timeouts) so throttle counters are
  shared across Gunicorn workers and the configured limits are exact
  instead of `N_workers ×`. Unset → per-process LocMem as before.
- Full suite **274 green**.

### S7 — `manage.py check --deploy` (VERIFIED CLEAN 2026-09-01)

- Ran against `config.settings.production` with representative env vars:
  **0 issues**. HSTS + preload, SSL redirect, secure/HttpOnly cookies,
  `nosniff`, referrer policy, `X-Frame-Options`, gated schema/docs — all
  already satisfied by `production.py` + the S1 additions to `base.py`.
  (The only warning ever emitted is `security.W009` when a deliberately
  weak `SECRET_KEY` is supplied — expected; a real random key is clean.)

### S6 — Dependency CVE patch (DONE 2026-09-01)

Conservative, same-line bumps only (no minor jumps that could shift
serializer / throttle behaviour):

| Package | Was | Now | Fixes |
|---|---|---|---|
| Django | 5.0.6 | **5.0.14** | ~15 CVEs across 5.0.7–5.0.14 (DoS in `strip_tags`/`urlize`/`floatformat`, IPv6 validation, `django.utils.http` redirect, SQL injection in `QuerySet.values()` on Oracle/JSON, etc.) |
| djangorestframework | 3.15.1 | **3.15.2** | CVE-2024-21520 (browsable-API stored XSS) |
| gunicorn | 22.0.0 | **23.0.0** | CVE-2024-6827 (HTTP request smuggling) |
| requests | pin 2.32.3 → **2.34.2** | (already installed) | CVE-2024-47081 (`.netrc` credential leak) |

- Pillow stays `10.3.0` — already past CVE-2024-28219; the app only decodes
  JPEG/PNG/WebP *headers* (never writes exotic formats), so the later
  Pillow CVEs don't apply. Revisit at the next major-version window.
- `requirements.txt` updated with a one-line CVE rationale per pin.
- Full suite **274 green** on the upgraded stack; `manage.py check` clean.

### S8 — Security regression test suite (DONE 2026-09-01)

- `apps/core/tests/test_security_headers.py` (8) — CSP / Permissions-Policy /
  nosniff / X-Frame / referrer present on web pages, API success, API 401,
  and 404; middleware unit tests for custom policy, report-only mode, and
  not clobbering a downstream CSP.
- `apps/accounts/tests/test_auth_throttling.py` (6) — login 429 + envelope,
  per-email keying, register/forgot-password caps, "no scope = no limit".
- `apps/students/tests/test_photo_upload_validation.py` (5) — size / format /
  dimension / disguised-payload rejection.
- Full suite **282 green**.

### S9 — Live 4-role verification (DONE 2026-09-01)

`scratchpad/sec_s9.py` + the existing role-journey scripts, against the live
dev server on the fully hardened stack:

| Check | Result |
|---|---|
| Security headers on web / API / 401 / 404 / login-200 | all present ✓ |
| Normal login (1–3 attempts) | never throttled ✓ |
| Burst (11th attempt within a minute) | `429 THROTTLED` ✓ |
| Different account, same client | not throttled — per-email keying ✓ |
| **Student** journey (login → profile → requirement → search → prefs → logout) | all 200/202, 60–170 ms (req POST ~0.9 s = eager Celery, unchanged) ✓ |
| **Teacher** journey (register → login → basic + marketplace profile → availability → verification → leads → unlock → wallet → plan → password → logout) | all green, 60–320 ms ✓ |
| **Admin** journey (approval login → users → students → teachers → verification round-trip → 6× CRUD → matching config → aliases → pincodes → password → logout) | all green, 60–270 ms; SA-only actions correctly 403 ✓ |
| **Super-Admin** smoke (me, dashboard, users, teacher-profiles, login-requests, ops health/events/overview, plans, matching, notifications) | all 200, 55–110 ms (ops/health ~0.8 s = dev broker ping, unchanged) ✓ |

No new delays, no unexpected errors, no interference with any role's actions.

---

## Bottom line

| | Before | After |
|---|---|---|
| Test suite | 274 | **282** (all green) |
| `manage.py check --deploy` | clean | clean (+ Redis-cache path) |
| Security response headers | prod only, no CSP | **all envs, CSP + Permissions-Policy + 4 more** |
| Auth brute-force ceiling | anon 100/h only | **per-account login cap + per-IP register/reset/admin-login caps** |
| Throttle at scale | per-worker LocMem | **shared-Redis option; all throttles fail-open** |
| Upload safety | none (any size/format) | **5 MB / 6000 px / JPEG-PNG-WebP, header-verified** |
| Request-body ceiling | Django defaults | **2 MB body, 2000 fields, 10 files** |
| Dependencies | Django 5.0.6, DRF 3.15.1, gunicorn 22 | **5.0.14 / 3.15.2 / 23** (CVE-patched) |

### Residual risks (documented, accepted)

1. **CSP allows `'unsafe-inline'` + `'unsafe-eval'` for scripts** — required by
   Alpine.js and the two inline `<script>` blocks. Mitigated by: template
   autoescape, no `|safe`/`mark_safe` on user data, angle-bracket + control-char
   field validators, JSON-only API renderer. To remove: migrate the frontend to
   the Alpine CSP build + nonce the inline scripts, then drop both keywords.
2. **No WAF / bot-management / DDoS scrubbing at the edge** — that is a
   deployment-infra concern (Cloudflare / AWS WAF / ALB), not an app change.
   The app-level rate limits are the floor, not the ceiling.
3. **Hard per-account lockout deliberately NOT added** — it would let an
   attacker lock a victim out by spamming their email. Per-account *throttling*
   (chosen) slows brute-force without that denial-of-service side effect.
4. **Password-reset email delivery still stubbed** (Phase 1) — when wired up,
   the reset link must be single-use + short-TTL (Django's token already is)
   and the email must not be logged in full.

---

## Follow-up: latency — city geocoding out of the request path (DONE 2026-09-01)

Found while reviewing the two "slow points" flagged in S9.

- The requirement POST's `validate_city` was making a **synchronous outbound
  Nominatim call** (`_try_geocode_city`, `requests` timeout 10 s + up to ~1 s
  rate-limit `sleep`) the first time any city name was submitted — so in
  production a student could wait seconds on a slow geocoder.
- `LocationResolutionService.resolve(location_text, *, defer_city_geocode=False)`
  — when `True`, resolves the `City` FK synchronously (fast exact/trigram DB
  match) but **skips** the centroid geocode. `StudentRequirementWriteSerializer.
  validate_city` passes `defer=True` **on create only** (`self.instance is None`);
  PATCH still resolves fully since it has no follow-up task.
- `process_requirement_leads._backfill_city_centroid()` fills in
  `pincode_location` from the city centroid before matching — best-effort, a
  geocoder outage never fails the task. Pincode input is still resolved
  synchronously (its coordinates are the location's identity, not enrichment).
- Net: requirement POST no longer blocks on an external HTTP call. Regression
  test `OfflineCityGeocodeRegressionTest.test_city_centroid_geocode_is_deferred_out_of_the_request`.
  Suite **283 green**.
- *Not changed* (declined): the same synchronous geocode in the **teacher-search**
  path (`apps/search/views.py`) — there the centroid is needed in-request to
  rank by distance, so it needs a different fix (tighter timeout / pre-seeded
  `City` centroids / caching).
