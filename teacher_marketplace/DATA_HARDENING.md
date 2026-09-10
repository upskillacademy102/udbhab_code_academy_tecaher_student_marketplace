# Data-quality hardening — 2026-09-01

Adding model validators + DB constraints + serializer normalisation to the write
endpoints so bad data can't get in. One endpoint at a time: harden → migrate →
test valid+junk → run full suite → run the role's live flow → next.

Reusable validators added in `apps/utils/validators.py`:
- `validate_no_control_characters` — rejects control chars + `<` `>`
- `validate_place_name` — city/state/country: must contain a letter; letters,
  digits, spaces, `. , ' - / ( ) &` only; 2–100 chars. Kills `12345`, `!!!`, `asdf<script>`.

Baseline before this work: **187 tests** (User model already had unique email +
unique mobile + name/mobile-format validators — nothing to add there).

---

## Endpoint 1 — Student profile  `POST/PUT/PATCH /api/v1/students/me/`  ✅

| Field | Before | After |
|-------|--------|-------|
| `bio` | `TextField` — unbounded | `CharField(max_length=1000)` → real `varchar(1000)` DB limit |
| `city` / `state` / `country` | free `CharField(100)` | `+ validate_place_name` |
| `grade_or_year` | free `CharField(50)` | `+ validate_no_control_characters` |
| `preferred_subjects` | trimmed only | trim + **dedupe (case-insensitive)** + max 15 entries + each ≤ 60 chars |
| all optional text | `""` and `"   "` stored as-is | serializer normalises `""`/whitespace → `NULL`; **DB `CheckConstraint`** `student_text_fields_not_blank` forbids a whitespace-only value in any of the 6 |
| `education_level` | already `choices` | unchanged |

Model + serializer: `apps/students/models.py`, `apps/students/serializers.py`.
Migration: `apps/students/migrations/0002_alter_student_bio_alter_student_city_and_more.py`
(one row had `bio=""` in dev — normalised to `NULL` first).
Regression: `apps/students/tests/test_profile_validation.py` (10). Suite 187 → 197.

**Verified:** realistic profiles + place names like `St. John's`, `Sector-21`
still save; `12345` / `!!!` / `asdf<script>` / 1001-char bio / 20 subjects /
control chars all rejected 400; live student flow (login → profile → requirement
→ search → preferences → logout) runs clean in 3.7 s, no new delays.

---

## Endpoint 2 — Student requirement + schedule preferences/exceptions ✅
`POST/PUT/PATCH /api/v1/student-requirements/` (+ `…/preferences/`, `…/schedule-exceptions/`,
`…/students/me/preferences/`)

| Field | Before | After |
|-------|--------|-------|
| `budget_min` / `budget_max` | `>= 0` only | `+ <= 1,000,000` ceiling; **DB CHECK** `budget_min <= budget_max` (was serializer-only) |
| `class_duration_minutes` | 5 preset `choices` (API), model claimed "any positive int" | 5 presets unchanged for the API; range validators + **DB CHECK 15–480** as a guard for non-API writes; help text corrected |
| `description` | `TextField` — unbounded | `CharField(max_length=2000)` → real `varchar(2000)` |
| `student_class` / `preferred_timing` | free text | `+ validate_no_control_characters` |
| `schedule_preferences` (inline) | uncapped list | **max 20** windows per requirement |
| `StudentSchedulePreference` | `start < end` serializer-only | **DB CHECK** `start_time < end_time`; **DB CHECK** timezone not blank |
| `StudentScheduleException.reason` | free text | `+ validate_no_control_characters`; **DB CHECK** not blank; serializer normalises `""` → NULL |
| all optional text on the requirement | `""` / `"   "` stored as-is | serializer → NULL; **DB CHECK** `requirement_text_fields_not_blank` |

Model + serializers: `apps/student_requirement/models.py`, `…/serializers.py`.
Migration: `apps/student_requirement/migrations/0005_alter_studentrequirement_budget_max_and_more.py`
(6 CHECK constraints; dev data was already clean).
Regression: `apps/student_requirement/tests/test_requirement_validation.py` (9).
Suite 197 → 206.

**Verified:** presets + `St. John's`-style data + 2000-char descriptions still
save; inverted/huge/negative budget, non-preset & out-of-range durations,
2001-char description, control chars, `<script>`, 21 windows, `end<start`,
bad timezone, `day_of_week 9` all 400; direct-DB writes that dodge the serializer
still hit the CHECK constraints. Live student flow unchanged, 3.2 s.

---

## Endpoint 3 — Teacher basic profile `POST/PUT/PATCH /api/v1/teachers/me/` ✅

| Field | Before | After |
|-------|--------|-------|
| `bio` | `TextField` unbounded | `CharField(max_length=2000)` |
| `qualification_detail` / `subjects_taught` | free text | `+ validate_no_control_characters` |
| `subjects_taught` | trim only | trim + case-insensitive dedupe + max 20 + each ≤ 60 chars |
| `city` / `state` / `country` | free `CharField(100)` | `+ validate_place_name` |
| `experience_years` | already `0–80` | unchanged |
| all optional text | `""` stored as-is | serializer → NULL; **DB CHECK** `teacher_text_fields_not_blank` |

Migration `apps/teachers/migrations/0003_alter_teacher_bio_alter_teacher_city_and_more.py`
(1 dev row had a `""` field — normalised first). Suite 206 → (see endpoint 4).

## Endpoint 4 — Teacher marketplace profile + availability ✅
`POST/PUT/PATCH /api/v1/teachers/profile/` (+ `…/weekly-availability/`, `…/schedule-exceptions/`)

| Field | Before | After |
|-------|--------|-------|
| `TeacherProfile.headline` | free `CharField(200)` | `+ validate_no_control_characters`; serializer → NULL on blank; **DB CHECK** not-blank |
| `TeacherProfile.hourly_rate` | `>= 0` only | `+ <= 1,000,000`; **DB CHECK** range |
| `subjects` / `languages` / `cities` (M2M) | uncapped | max 30 / 15 / 30 |
| `TeacherWeeklyAvailability` | `start < end` + tz in `clean()` (needs `full_clean`) | **DB CHECK** `start_time < end_time`; **DB CHECK** timezone not blank |
| `TeacherScheduleException.reason` | free text | `+ validate_no_control_characters`; **DB CHECK** not-blank |
| `TeacherScheduleException` times | serializer-only pair check | **DB CHECK** both-set-or-both-null; **DB CHECK** `start < end` |

Migrations: `apps/teacher_profile/migrations/0003_…` + `0004_…` (dev data clean).
Regression: `apps/teacher_profile/tests/test_profile_validation.py` (9),
`apps/students/tests/test_profile_validation.py` (10),
`apps/student_requirement/tests/test_requirement_validation.py` (9). **Suite 187 → 215.**

**Verified:** full teacher journey (register → basic → marketplace → availability
→ verification → leads → unlock → wallet → subscription → change password →
logout) runs clean; junk (`experience 200`, `hourly_rate 10M`, `<headline>`,
control chars, 40 subjects, `end<start`, bad tz, half-specified time range) all
400; direct-DB writes hit the CHECK constraints.

---

## Pre-existing bug — `POST /payments/create-order/` 500 (FIXED ✅ 2026-09-01)

`PaymentService.create_order` called `client.order.create({...})` with no error
handling → a Razorpay outage / SSL / network failure / placeholder keys bubbled a
raw **500 with a stack trace**. Surfaced once there were token packages to order.

**Fix** (`apps/payments/services.py`):
- `_razorpay_is_configured()` — short-circuits to a clean **503
  `SERVICE_UNAVAILABLE`** when the keys are missing or still placeholders
  (`your_key`, `changeme`, …) — no pointless network call (dev/staging path).
- `try/except` around `client.order.create` catching `razorpay.errors`
  (`BadRequestError` / `GatewayError` / `ServerError`) **and**
  `requests.exceptions.RequestException` → `ServiceUnavailableException` (503),
  logged with `exc_info` for ops. Also guards a malformed order payload.
- No dangling `PENDING` `Payment` row is created on failure.

Invalid input still returns 400; the happy path is unchanged. Now ~96 ms instead
of a ~700 ms SSL-retry hang. Regression:
`apps/payments/tests/test_create_order.py` (5). Suite 215 → 220.

---

# Admin / Super-Admin write endpoints

New validators in `apps/utils/validators.py`:
- `validate_taxonomy_name` — subject/language/plan/package/tier display names:
  must contain a letter; letters, digits, spaces, `. , ' - / ( ) & + #`; 2–150.
  Accepts `C++`, `Class 9 & 10`, `English (US)`. Kills `12345`, `!!!`, `<x>`.
- `validate_language_code` — `^[A-Za-z][A-Za-z0-9-]{1,9}$` (`en`, `pt-br`).

## Task A1 — Subjects + Languages ✅
`POST/PUT/PATCH/DELETE /api/v1/subjects/` · `/api/v1/languages/`

| Field | Before | After |
|-------|--------|-------|
| `Subject.name` / `Language.name` | free `CharField` (unique) | `+ validate_taxonomy_name`; serializer strips; **DB CHECK** not-blank |
| `Subject.description` | `TextField` unbounded | `CharField(max_length=1000)`; serializer `""`→NULL; **DB CHECK** not-blank |
| `Subject.icon` | free `CharField(100)` | `+ validate_no_control_characters`; `""`→NULL; **DB CHECK** not-blank |
| `Language.code` | free `CharField(10)` (unique, lowercased on save) | `+ validate_language_code`; serializer lowercases; **DB CHECK** `code ~ '^[a-z][a-z0-9-]{1,9}$'` + not-blank |

Migrations `apps/subjects/migrations/0002`, `apps/languages/migrations/0002`
(one dev subject had `icon=""` — normalised first).
Regression: `apps/subjects/tests/test_taxonomy_validation.py` (8). Suite 220 → 228.
**Verified:** `C++`, `Class 9 & 10`, `PT-BR`→`pt-br` save; all-digit / all-punct /
`<x>` / control-char / blank names + bad codes + 1001-char descriptions all 400;
direct-DB blank-name / bad-code writes hit the CHECK constraints. Student, teacher
& admin flows unchanged.

## Task A2 — Locations (countries / states / cities) ✅
`POST/PUT/PATCH/DELETE /api/v1/location/{countries,states,cities}/`

| Field | Before | After |
|-------|--------|-------|
| `Country.name` / `State.name` / `City.name` | free `CharField(150)` | `+ validate_place_name`; serializer strips; **DB CHECK** not-blank |
| `Country.code` | free `CharField(3)` (unique, uppercased on save) | `+ validate_country_code` (`^[A-Za-z]{2,3}$`); serializer uppercases; **DB CHECK** `code ~ '^[A-Z]{2,3}$'` |
| `State.code` | free nullable `CharField(10)` | `+ validate_no_control_characters`; serializer `""`→NULL; **DB CHECK** not-blank |

Migration `apps/location/migrations/0002` (needed a cleanup first — 27 soft-deleted
`Audit*`/`ZZ`/`Probe*` junk rows from earlier admin probe scripts were hard-deleted,
one had a digit in its country code).
Regression: `apps/location/tests/test_location_validation.py` (7). Suite 228 → 235.
**Verified:** lowercase/mixed codes normalise; `St. Mary's Province`,
`Stratford-upon-Avon` save; digit/4-letter codes, all-digit/blank/`<>` names all 400.

## Task A3 — Token packages ✅  `/api/v1/token-packages/`
`name` → `validate_taxonomy_name` + not-blank DB CHECK; serializer strips.
`token_count` 1..1,000,000 · `price` 0..1,000,000 · `gst_percentage` /
`discount_percentage` 0..100 · `sort_order` ≤ 100,000 — one
`token_package_sane_ranges` DB CHECK. Migration `apps/payments/migrations/0003`.
Regression `apps/payments/tests/test_token_package_validation.py` (4). Suite 235 → 239.

## Task A4 — Subscription plans ✅  `/api/v1/subscriptions/plans/`
`name` → `validate_taxonomy_name` + not-blank DB CHECK. `monthly_price`
0..1,000,000 · `free_leads` ≤ 100,000 · `priority_rank` ≤ 1,000 ·
`lead_multiplier` 0..10 · `bonus_tokens` ≤ 1,000,000 — one
`subscription_plan_sane_ranges` DB CHECK. Migration `apps/subscriptions/migrations/0003`.

## Task A5 — Lead unlock pricing ✅  `/api/v1/lead-unlock-pricing/`
`token_cost` 1..100,000 + `lead_unlock_pricing_token_cost_range` DB CHECK.
Migration `apps/lead_engine/migrations/0006`. Regression (A4+A5)
`apps/subscriptions/tests/test_plan_validation.py` (7). Suite 239 → 246.

## Task A6 — Matching engine (config / aliases / pincodes) ✅
`/api/v1/matching/{config,subject-aliases,language-aliases,pincode-locations}/`
- **MatchingConfig**: thresholds ≤ 100 · minutes 1..1,440 · radii 1..5,000
  (+ `initial ≤ max`, serializer + DB) · hours 1..720 ·
  `subscription_priority_order` = ≤ 20 unique non-empty strings — one
  `matching_config_sane_ranges` DB CHECK.
- **Subject/Language aliases**: `alias_text` stripped, not-blank (serializer +
  DB CHECK), no control chars.
- **PincodeLocation**: latitude −90..90, longitude −180..180 (serializer field
  bounds) · `pincode` not-blank (+ DB CHECK) · `city`/`state`/`country` →
  `validate_place_name`, `""`→NULL.
Migration `apps/matching/migrations/0003`.
Regression `apps/matching/tests/test_admin_config_validation.py` (9). Suite 246 → 255.

## Task A7 — Super-Admin user management ✅
`POST /api/v1/admin/users/` · `PATCH /api/v1/admin/users/{id}/`
The `User` model already had unique email + unique mobile + name/mobile format,
but the admin serializers are plain `Serializer`s so **none of it ran**: an admin
could create `mobile="abc"` / `first_name="John123"`, and PATCHing a colliding
mobile **500'd on IntegrityError**.
- `validate_name` + `validate_mobile_number` on the serializer fields (+ `max_length`).
- Name trimming (`_normalise_name`).
- Mobile-uniqueness check on **update** (excluding the target) → clean 400 not 500.
- Password already went through Django's validators (incl. `PasswordStrengthValidator`).
Serializer-only (no migration). Regression
`apps/accounts/tests/test_admin_user_validation.py` (8). Suite 255 → 263.

---

## Summary
| Area | Endpoints hardened | Tests | Suite |
|------|--------------------|-------|-------|
| Student | profile, requirement (+prefs/exceptions) | 19 | → 206 |
| Teacher | basic profile, marketplace profile, availability, exceptions | 18 | → 215 |
| Payments bug | create-order 500 → clean 503 | 5 | → 220 |
| Admin taxonomy | subjects, languages | 8 | → 228 |
| Admin locations | countries, states, cities | 7 | → 235 |
| Admin commerce | token packages, plans, lead pricing | 11 | → 246 |
| Admin matching | config, aliases, pincodes | 9 | → 255 |
| Super-admin users | create, update | 8 | → 263 |

**Baseline 187 → 263 tests, all green.** Student / teacher / admin live journeys
all run clean with no new delays. Every rule enforced at both the API layer (clean
400) and the database layer (`CHECK` / `varchar(n)` / field bounds).
