# Fake-lead reports → Super Admin alerts + automatic ban

Teachers rate every lead they unlock. A "fake" rating is a report: it lands
on the Super Admin dashboard immediately, and enough distinct teachers
reporting one student bans that student automatically. Built 2026-09-09.

---

## 1. The teacher side — rate every unlocked lead

Rating already existed (`POST /api/v1/leads/{id}/rate/`, verdicts
`genuine` / `unreachable` / `fake`). What's new is that it's now **expected
for every unlock**, and surfaced so teachers actually do it:

| Surface | What shows |
|---|---|
| Lead detail | The "Rate this lead" card is highlighted (amber border) until rated, and shows the verdict once done. `Fake` is a red button. |
| Leads list | An amber banner — *"N leads need your rating"* — links to the next one. Each unlocked-but-unrated card shows *"Unlocked — tap to rate this lead"*. |
| Teacher dashboard | A nudge card when `pending_rating_count > 0`. |
| API | `GET /api/v1/leads/pending-ratings/` → `{count, results}`; `pending_rating_count` on `GET /api/v1/dashboard/`; `my_rating` on every lead serializer. |

It is a **prompt, not a hard gate** — a teacher is never blocked from
unlocking the next lead by an unrated one (they often haven't phoned the
student yet).

---

## 2. Every "fake" rating → a Super Admin alert

`LeadQualityService._reassess_fake_reports` runs on every fake rating and
opens or updates one `FAKE_LEAD_REPORT` review item per student (deduped
`flr:{student_id}`), carrying live counts in its payload:

```
distinct_teachers_7d / _30d / _all   total_reports
latest_report {teacher, lead, subject, note, at}
student_email / student_name         auto_banned
```

Priority rises with the counts (3 → 2 at ≥3 distinct teachers → 1 once
auto-banned or ≥5 in a week).

**Where the Super Admin sees it:**
- **Dashboard** (`/super-admin/`) — a red "Fake-lead reports" panel with
  per-student counts, the latest report, and **View / Suspend / Ban /
  Reactivate** buttons inline. Fed by `fake_lead_alerts` on
  `GET /api/v1/dashboard/` (Super Admin only) and
  `GET /api/v1/ops/fake-lead-reports/`.
- **Review queue** (`/super-admin/review-queue/?kind=fake_lead_report`) —
  same item with the same action buttons plus resolve/dismiss.

---

## 3. Counting — distinct teachers, with a floor

Counting is **by distinct teacher**, not by report. A teacher who flags
five of one student's leads counts once — that's the anti-gaming property.
Windows are rolling (`updated_at` within 7 / 30 days), so a stale report
ages out and a changed verdict (fake → genuine) drops the count live.

`FAKE_LEAD_AUTOBAN_MIN_DISTINCT_TEACHERS` (3) is a hard floor: **no
automatic ban ever fires below it**, whatever the window thresholds are set
to. One or two teachers acting together can never get a student banned.

---

## 4. Automatic ban

Always on — **no feature flag** (deliberate: this is a safety mechanism,
not an optional enforcement escalation). A student is **permanently
banned** the moment:

> `distinct_teachers_7d > FAKE_LEAD_AUTOBAN_WEEKLY` (10)
> **or** `distinct_teachers_30d > FAKE_LEAD_AUTOBAN_MONTHLY` (15)
> **and** `distinct_teachers_all ≥ FAKE_LEAD_AUTOBAN_MIN_DISTINCT_TEACHERS` (3)

A ban = `User.is_active = False` + every active `UserSession` killed +
an `AccountSanction` row (`source = auto_fake_leads_weekly|monthly`,
`created_by = null`). It **does not lift on its own** — only a Super Admin
reactivating the account clears it. The `FAKE_LEAD_REPORT` alert stays open
with `auto_banned: true` at priority 1 so the Super Admin reviews every
automatic ban.

Idempotent: once a student has an active sanction, further fake reports
update the alert but never stack a second ban.

---

## 5. Ban / Suspend / Reactivate (manual)

`AccountSanction` (`apps/trust`) + `SanctionService`:

| Action | Effect |
|---|---|
| **Ban** (`kind=ban`) | Deactivate + kill sessions. Permanent until reactivated. |
| **Suspend** (`kind=suspend`) | Mechanically identical to Ban — same deactivation, no auto-lift. The kind is recorded for the Super Admin's own tracking (a suspension reads as "temporary, revisit"). |
| **Reactivate** | `SanctionService.lift` — `is_active = True`, sanction marked lifted with actor + reason. |

Endpoints (Super Admin only, via the ops permission short-circuit):

```
GET  /api/v1/ops/sanctions/               list (filter ?active= ?user=)
POST /api/v1/ops/sanctions/               {user_id, kind, reason, review_item_id?}
POST /api/v1/ops/sanctions/{id}/lift/     {reason}
GET  /api/v1/ops/fake-lead-reports/       the dashboard feed
```

Admin and Super Admin accounts cannot be sanctioned. Every action is written
to the audit log.

---

## 6. Settings

| Setting | Default | Meaning |
|---|---:|---|
| `FAKE_LEAD_AUTOBAN_WEEKLY` | 10 | distinct teachers in 7 days that trips a ban (strict `>`) |
| `FAKE_LEAD_AUTOBAN_MONTHLY` | 15 | distinct teachers in 30 days (strict `>`) |
| `FAKE_LEAD_AUTOBAN_MIN_DISTINCT_TEACHERS` | 3 | hard floor — no auto-ban below this |
| `FAKE_LEAD_REPORT_WEEKLY_WINDOW_DAYS` | 7 | |
| `FAKE_LEAD_REPORT_MONTHLY_WINDOW_DAYS` | 30 | |

`test.py` pins the two thresholds to 10 000 so the general suite is
deterministic; `apps/trust/tests/test_fake_lead_reports.py` overrides them
back down to exercise the ban path (same tactic as
`TRUST_CAPTCHA_SWITCH_THRESHOLD`).

---

## 7. What changed in code

| Area | Change |
|---|---|
| `trust/models.py` | `ManualReviewKind.FAKE_LEAD_REPORT`; `AccountSanction` + kinds/sources (migration `trust/0014`) |
| `trust/services/sanction_service.py` | new — `apply` / `lift` / `active_for` |
| `trust/services/lead_quality_service.py` | `_reassess_fake_reports`, `fake_report_stats`, `_open_fake_report_item`; clawback now creates the wallet before refunding (**pre-existing bug** — an allowance-only teacher had no Wallet row) |
| `ops/views.py` + `urls.py` + `serializers.py` | `OpsFakeLeadReportsView`, `OpsSanctionListCreateView`, `OpsSanctionLiftView` |
| `lead_engine/views.py` + `serializers.py` | `PendingRatingsView`; `my_rating` / `contact_unlocked` on the lead serializers; context wiring |
| `analytics/views.py` | `pending_rating_count` (teacher); `fake_lead_alerts` (Super Admin) |
| `accounts/api_permissions.py` | `lead_engine:pending-ratings` → teacher |
| Web | Super Admin dashboard panel + review-queue buttons/kind; teacher leads banner + per-card chip + lead-detail prominence + dashboard nudge |

Tests: `apps/trust/tests/test_fake_lead_reports.py` (17). Suite 606 → 623.

---

## 8. Trade-offs / notes

- **No appeal path for an auto-ban.** The existing `SuspensionAppeal` flow
  only covers *risk*-suspension (`TRUST_ENABLE_RISK_AUTO_ACTIONS`), not
  these `is_active=False` bans. A banned student can't log in to appeal —
  they'd contact `SUPPORT_EMAIL`. If auto-bans turn out to need self-service
  appeals, that's a follow-up.
- **10 distinct teachers is a strong bar**, but a genuinely popular student
  who posts many requirements and gets unlucky with a few unresponsive
  teachers could accumulate reports. The distinct-teacher counting and the
  rolling window blunt this; watch the review queue after launch.
- **Suspend == Ban mechanically.** If you later want suspend to be a
  softer, time-boxed state, `SanctionService` is the one place to change.
