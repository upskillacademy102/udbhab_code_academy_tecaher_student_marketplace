# Security Audit — 2026-08-31

Adversarial testing of role isolation and business-rule bypass. Method: two live
accounts of the same role, one attacks the other's data through the real API;
plus attempts to escalate privilege and skip payment/quota gates.

**Result key:** PASS = attack correctly blocked, no data leak, no 500.

---

## Part 1 — Teacher security  ✅ CLEAN (0 vulnerabilities)

~40 attack checks run live (`scratchpad/sec_teacher*.py`), then locked in as
regression tests: `apps/lead_engine/tests/test_lead_pipeline.py::TeacherIsolationSecurityTests`
(10) + the pre-existing `LeadSecurityTests` (3).

### Cross-teacher data access — all blocked
| Attack | Result |
|--------|--------|
| A reads B's lead by id (`GET /leads/{B_lead}/`) | 404 (existence not leaked) |
| A reads B's lead match breakdown (`/leads/{B_lead}/matches/`) | 404 |
| A reads B's teacher profile (`GET /teachers/{B_id}/`) | 403 (route is Student/Admin only) |
| A reads B's best-slots | 403 |
| A uses `/teachers/` list or `/search/teachers/` | 403 (teacher-discovery is not for teachers) |
| A's lead list / unlock-history | contains only A's rows |

### Cross-teacher writes / actions — all blocked
| Attack | Result |
|--------|--------|
| A unlocks B's lead | 404; B's lead stays locked |
| A accepts / rejects B's lead assignment | 404; assignment status unchanged |
| A deletes / patches B's weekly-availability slot | 404; slot unchanged |
| A deletes B's schedule exception | 404 |

### Privilege escalation — all blocked
| Attack | Result |
|--------|--------|
| A self-verifies via `POST /teachers/profile/ {verification_status:"verified"}` | field not in write serializer → ignored; stays `pending` |
| A self-verifies via `PATCH /teachers/me/` | ignored (admin-only, set through `/admin/teacher-profiles/{id}/verification/`) |
| A sets own `rating: "5.00"` | field read-only → ignored |
| A writes to `/wallet/` (PATCH/POST a balance) | 403/405 — no client-writable balance path exists |

### Business-rule bypass — all blocked
| Attack | Result |
|--------|--------|
| Unlock the same lead twice | 2nd → 400 "already unlocked"; wallet charged **once** |
| Unlock with 0 free quota + empty wallet | 400 `INSUFFICIENT_BALANCE_FOR_UNLOCK`; lead stays locked (not a 500) |
| Unlock a non-existent lead id | 404 |
| Activate a paid plan with no `payment_id` | 400 |
| Activate with a bogus/random `payment_id` | 400 "Payment not found" |
| A activates a paid plan using **B's** (real, SUCCESS) payment row | 400 (payment is teacher-scoped) |

### Role boundary (teacher → other surfaces) — all 403
`/students/`, `/students/{id}/`, `/student-requirements/` (GET + POST),
`/admin/users/`, `/admin/teacher-profiles/`, `/admin/teacher-profiles/{id}/verification/`,
`/ops/health/`, `/ops/events/`, `/matching/config/` (POST), `/subjects/` (POST),
`/admin/users/{id}/impersonate/`.

### Minor notes (not vulnerabilities)
- Concurrent double-unlock of one lead: the `LeadUnlockHistory` unique
  `(teacher, lead)` constraint prevents any double-charge, but the losing request
  surfaces the `IntegrityError` as a generic 500 rather than a clean "already
  unlocked" 400. Needs genuine concurrency; no data/financial corruption. Low
  priority — could add `select_for_update` on the lead row in `unlock_lead_contact`.

---

## Part 2 — Student security  ✅ CLEAN (0 vulnerabilities)

46 attack checks run live (`scratchpad/sec_student.py`), locked in as
`apps/student_requirement/tests/test_student_security.py::StudentIsolationSecurityTests` (8).

### Cross-student data access / mutation — all blocked
| Attack | Result |
|--------|--------|
| A reads B's requirement (`GET /student-requirements/{B}/`) | 404 |
| A edits B's requirement (PATCH / PUT) | 404; B's data unchanged |
| A deletes B's requirement | 404 |
| A's own requirement list | excludes B's |
| A lists B's schedule preferences (`?requirement_id=<B>`) | 404 |
| A adds a preference to B's requirement | 404 |
| A patches / deletes B's preference by id | 404 |
| A lists / adds / deletes B's schedule exceptions | 404 |
| Same attacks via the `/students/me/preferences/` mount | 404 |
| A lists students / reads a student by id (`/students/`, `/students/{id}/`) | 403 (people search is Admin-only) |

### Privilege escalation — blocked
| Attack | Result |
|--------|--------|
| `PATCH /students/me/ {role:"admin", is_staff:true, is_superuser:true}` | 200, but `role`/`is_staff`/`is_superuser` aren't in the write serializer → silently ignored; account stays a plain student |

### Teacher / admin surfaces — all 403 for a student
`/leads/`, `/leads/unlock/`, `/leads/unlock-history/`, `/matching/assignments/`,
`/wallet/`, `/wallet/history/`, `/subscriptions/`, `/subscriptions/quota/`,
`/subscriptions/activate/`, `/payments/`, `/payments/create-order/`, `/dashboard/`,
`/teachers/me/`, `/teachers/profile/…`, `/admin/*`, `/ops/*`, `/matching/config/`,
`POST /subjects/`, `/admin/users/{id}/impersonate/`.

### Requirement validation — cannot be bypassed
`budget_min > budget_max` → 400 · offline requirement with no city → 400 ·
unknown subject text → 400 · second OPEN requirement for the same subject+mode → 400.

### Free teacher-browse does not leak
`/search/teachers/` cards and `GET /teachers/{id}/` carry **no** teacher email or
mobile (`PublicUserSerializer`). Direct contact stays unlock-gated through the
lead flow.

---

## Verdict
Both roles' data-isolation and business-rule gates hold under adversarial testing.
**Test suite: 146 → 179** (13 new security regression tests). No code changes were
needed for security — the existing "scope every queryset to `request.user`, 404
(not 403) on someone else's id" pattern is applied consistently, and the
centralised `RoleBasedAPIPermission` registry is the real boundary.

One low-priority hardening item (concurrent double-unlock → 500 instead of clean
400; no financial impact) noted above.
