# Frontend (`apps/web`)

Two layers, one origin, one stylesheet.

**Django templates + Tailwind + Alpine** serve the public pages (landing, login,
register, errors) and every student/teacher/admin page that hasn't moved yet.

**A React + Vite SPA** (`frontend/`) owns pages behind the login, mounted into the
same `base_app.html` shell so the sidebar, topbar and guards are unchanged. It is
being moved across a page at a time — `/student/` (Discover) is the first.

Everything is served by Django on a single origin, so the httpOnly `access`
cookie works identically in both layers. There is no separate dev server.

## Working on the SPA

```powershell
cd frontend
npm install
npm run build      # one-off
npm run dev        # vite build --watch — rewrites static/app/ on save
```

`npm run dev` is a watching build, not an HMR dev server. Two servers would mean
two origins, and the auth cookie only belongs to one of them. Slightly slower;
auth behaves exactly as it does in production.

`static/app/` is committed (like `static/css/app.css`) so a checkout runs without
Node installed. `apps/web/vite.py` reads Vite's `manifest.json` to resolve hashed
filenames; if the bundle is missing the shell says so instead of 404-ing a script.

**Tailwind scans `frontend/src/**/*.{ts,tsx}`** — both layers share
`static/css/app.css`, so the SPA cannot drift from the public pages.

```
apps/web/
  guards.py        role_required() — resolves the user from the auth cookie (same as the API)
  nav.py           single source of role-aware navigation
  urls.py          every page; page(template, roles=..., title=...) factory
  views.py         thin views + branded 403/404/500 handlers
  context.py       SITE_NAME, web_user, web_role, web_home into every template
  templatetags/web_extras.py   {% icon %}, {% nav_for %}, {% nav_active %}, |initials

templates/web/
  base.html            <head>, fonts, css, Alpine + plugins, toast/confirm regions
  base_app.html        authenticated shell: sidebar + topbar + page header
  base_public.html     split-screen shell for landing/login
  _icons.html          inline SVG sprite
  partials/            _card_skeleton, _row_skeleton, _error, _pagination, _teacher_card
  {student,teacher,admin,superadmin}/   role pages
  errors/              403 / 404 / 500

static/
  src/app.css          design-system source (@layer components: .btn/.card/.input/...)
  css/app.css          BUILT stylesheet (committed) — regenerate with tools/build-css.ps1
  js/
    api.js             the one API client — auth 401→login, 403 toast, 409, envelope unwrap
    app.js             toasts, confirm dialog, fmt.* formatters
    pages.js           mk.collection / mk.record / mk.apiForm — loading/empty/error/pagination
    admin.js           RESOURCE_CONFIG + resourceManager (generic admin CRUD)
    auth.js            login form (routes by real role)
    vendor/            alpine + collapse + focus plugins (pinned, committed)
  fonts/               Inter variable subset (committed)
```

## Running

```powershell
python manage.py runserver
# during design work, in a second terminal, rebuild CSS on save:
./tools/build-css.ps1 -Watch
```

Visit `/` → choose Student or Teacher → log in. Admin / Super Admin accounts log in
through the same form (no separate button) and land in their own area.

## Changing styles

Edit `static/src/app.css` or template classes, then:

```powershell
./tools/build-css.ps1        # one-off, minified — run before committing
```

The 38 MB `tools/tailwindcss.exe` is **not** committed. Download it from
<https://github.com/tailwindlabs/tailwindcss/releases> (`tailwindcss-windows-x64.exe`).

## Security model

Route guards (`role_required`) stop a user *seeing* a page they can't use, and turn a
hand-typed forbidden URL into a friendly 403. **The DRF API's `RoleBasedAPIPermission`
remains the real authorisation boundary** — every data call the browser makes is
re-authorised server-side.

## Privileged access (all live)

- **Staff sign-in** — `/login/staff/` (unlinked; staff know the URL). Super Admin signs in
  directly; **Admin** submits credentials → a pending `AdminLoginRequest` → an online Super
  Admin approves it at `/super-admin/admin-requests/` → the admin's session is issued.
  `/api/v1/auth/login/` now **rejects** `role=admin` (gated by `ADMIN_LOGIN_REQUIRES_APPROVAL`).
- **User management** — `/super-admin/users/` (also read-only for admins at `/admin-portal/users/`):
  list/search/filter, create, role change, activate/deactivate (deactivate kills sessions).
  API: `/api/v1/admin/users/…` (`admin_api.py` + `admin_users_urls.py`).
- **Impersonation** — "Act as this user" on a user's drawer → `POST /admin/users/{id}/impersonate/`.
  Uses a separate `ImpersonationSession` (the target's real session is untouched), 30-min TTL,
  token carries an `act` claim. A persistent amber banner ("Viewing as X — Return to your
  account") shows on every page → `POST /auth/stop-impersonation/`. Fully audited.
- **Audit log** — `apps/ops` `AuditLog` (append-only, `AuditService.record`). Feed at
  `/super-admin/audit/` ← `GET /api/v1/ops/events/`.
- **Operations** — `/super-admin/oversight/` ← `GET /api/v1/ops/{health,overview,errors}/`
  (DB/cache/celery/migrations health, platform KPIs, redacted error-log tail). Super-Admin only.

See `apps/accounts/tests/test_privileged_access.py` for coverage.
