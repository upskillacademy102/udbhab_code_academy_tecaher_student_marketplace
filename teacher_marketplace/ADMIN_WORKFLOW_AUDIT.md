# Admin Workflow Audit — 2026-08-31

Walking every task a real Admin performs on the site, in order, exactly as the
admin frontend calls the API. Recording every bug, hindrance, and delay. Fixing
one at a time (no parallel fixes unless tightly coupled).

## Journey steps

1. Staff sign-in via the approval flow (`POST /auth/admin/login/` → superadmin
   approves → `GET /auth/admin/login/{id}/status/?token=`)
2. Platform dashboard (`GET /dashboard/`)
3. Users — list / search / filter by role + status (`GET /admin/users/`)
4. Students — list / filter by city (`GET /students/`), open one (`GET /students/{id}/`)
5. Teachers — list / filter (`GET /teachers/`), open one (`GET /teachers/{id}/`
   + `GET /admin/teacher-profiles/{id}/`)
6. Teacher verification — verify / revoke / reject
   (`POST /admin/teacher-profiles/{id}/verification/`)
7. Subjects — create / edit / delete (`/subjects/`)
8. Languages — create / edit / delete (`/languages/`)
9. Locations — countries / states / cities create / edit / delete (`/location/…`)
10. Token packages — create / edit / delete (`/token-packages/`)
11. Subscription plans — create / edit / delete (`/subscriptions/plans/`)
12. Lead unlock pricing — create / edit / delete (`/lead-unlock-pricing/`)
13. Matching config — append a new active config (`POST /matching/config/`)
14. Subject aliases — add (`POST /matching/subject-aliases/`)
15. Language aliases — add (`POST /matching/language-aliases/`)
16. Pincode locations — add (`POST /matching/pincode-locations/`)
17. Notifications (`GET /notifications/`)
18. Change password, logout

## Findings (full walkthrough via `scratchpad/admin_journey.py` + `admin_probe2.py`)

The happy path is **clean** — staff sign-in, dashboard, user/student/teacher
browsing, teacher verification round-trips, and full create/edit/delete on
subjects, languages, locations, token packages, plans, pricing, matching config,
aliases and pincodes all return 2xx in 50–290 ms. No 500s. Admin correctly gets
403 on the Super-Admin-only actions (create user, change role, deactivate,
impersonate). Staff sign-in end-to-end ≈ 1.2 s (two logins + approve + poll).

| # | Severity | Area | Symptom |
|---|----------|------|---------|
| 1 | **P1 hindrance** | Commerce → Token Packages / Subscription Plans / Lead Unlock Pricing | Deactivating an item (`is_active=false` / `status=inactive`) makes it **vanish from the admin's own management list** — the list endpoints hard-filter to active rows. The admin then has no way to see it, edit it, or re-activate it through the UI. (The row still exists; `GET /…/{id}/` works; but the UI never surfaces the id.) The frontend even renders an "Inactive" badge that is dead code because the API never returns inactive rows. |
| 2 | **P2 hindrance** | Commerce (Plans, Lead Pricing, Token Packages) + Matching Engine (Config, Subject/Language Aliases, Pincodes) | The search box on these ~6 resource pages **does nothing** — `resourceManager` sends `?search=<q>` but these list views have no `SearchFilter`, so the param is silently ignored and the list never filters. Subjects & Languages search works (they have `SearchFilter`). |
| 3 | P3 minor | Matching Engine → Pincode Locations | The Add form marks Latitude/Longitude as optional (no `*`), but the API requires them → filling just pincode + city gives a confusing "This field is required." 400. |
| — | not a bug | Matching Config list | Returns a paginated `{count,next,previous,results}` envelope; the frontend unwraps `.results` correctly. |
| — | not a bug | Lead Pricing "create" | One row per tier is enforced; all 4 tiers are seeded, so "Add" 400s with "already exists". Admin is expected to **edit** the tier row, not add. |

Priority order for fixes: **1** (data becomes unmanageable) → **2** (search) → **3** (form labels).

---

## Fix log

### Bug 1 — deactivated commercial items vanished from the admin list (FIXED ✅)
- **Root cause:** `TokenPackageListCreateView`, `SubscriptionPlanListCreateView`
  and `LeadUnlockPricingListCreateView` all hard-coded
  `queryset = …objects.filter(is_active=True / status="active")`. That queryset
  serves both the teacher-facing buy/subscribe pages **and** the admin management
  pages, so once an admin deactivated an item it disappeared from their own list
  and could never be re-activated through the UI.
- **Fix:** added `User.is_platform_staff` (Admin or Super Admin) in
  `apps/accounts/models.py`, and made all three list views role-aware in
  `get_queryset()` — platform staff get every row, teachers still get active rows
  only. Detail views were already unrestricted.
  Files: `apps/payments/views.py`, `apps/subscriptions/views.py`,
  `apps/lead_engine/views.py`, `apps/accounts/models.py`.
- **Regression:** `apps/subscriptions/tests/test_catalog_visibility.py::AdminCatalogVisibilityTests`
  (6 — teacher sees active-only, admin sees inactive too, for all three resources).
  Suite 179 → 185.
- **Verified live:** admin now keeps inactive token packages / plans / pricing in
  the list; teacher `GET /token-packages/` and `/subscriptions/plans/` still
  exclude them.

### Bug 2 — admin resource search box was a no-op on 6 pages (FIXED ✅)
- **Root cause:** `resourceManager` (admin.js) sends `?search=<q>`, but
  `TokenPackageListCreateView`, `SubscriptionPlanListCreateView`,
  `LeadUnlockPricingListCreateView`, `SubjectAliasListCreateView`,
  `LanguageAliasListCreateView`, and `PincodeLocationListCreateView` had no
  `SearchFilter` in `filter_backends` (the global default is `DjangoFilterBackend`
  only). DRF silently ignored the param.
- **Fix:** added `filter_backends = [SearchFilter]` + `search_fields` to each:
  packages/plans by `name`, pricing by `tier`, aliases by `alias_text` +
  linked-name, pincodes by `pincode`/`city`/`state`/`country`.
  Files: `apps/payments/views.py`, `apps/subscriptions/views.py`,
  `apps/lead_engine/views.py`, `apps/matching/views.py`.
  (Matching Config left alone — numeric config, append-only, nothing to search.)
- **Regression:** `AdminResourceSearchTests` in the same test file (2). Suite 185 → 187.
- **Verified live:** every one of the 6 search boxes now filters; a nonsense term
  returns 0 rows.

### Bug 3 — Pincode form said Lat/Long were optional; the API required them (FIXED ✅)
- **Root cause:** `admin.js` `pincodes` field config didn't mark `latitude` /
  `longitude` `required`, but `PincodeLocationSerializer` has them as plain
  (required) `FloatField`s → an admin filling only pincode + city got a bare
  "This field is required." 400.
- **Fix:** marked both `required: true` in the `pincodes` config with a
  "decimal degrees, e.g. 22.5726" hint, so the form shows the `*` and the inline
  error lands on the right field. (`static/js/admin.js` — served directly, no
  build step.)
- Kept minimal: a geocode-from-pincode fallback (like the teacher pincode flow)
  would be nicer but is network-dependent scope creep — logged as a future idea.

---

## Status: admin workflow — CLEARED
Full journey (staff sign-in → dashboard → users/students/teachers browse →
verification round-trips → subjects/languages/locations/token-packages/plans/
pricing/config/aliases/pincodes CRUD → notifications → change password → logout)
runs end-to-end with no 4xx/5xx except the one intentional 400 (one pricing row
per tier; all tiers seeded → "Add" is expected to fail, admin edits instead).
Every step 50–290 ms; staff sign-in ~0.45 s (Argon2). Suite: **187 passing**.

Fixed this pass: Bug 1 (deactivated catalog items vanished), Bug 2 (dead search
boxes), Bug 3 (pincode form label mismatch).
