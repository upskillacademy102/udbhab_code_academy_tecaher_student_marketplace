/**
 * Shapes returned by the DRF API.
 *
 * Written against the actual serializers, not guessed:
 *   TeacherProfileSerializer  apps/teacher_profile/serializers.py
 *   StudentSerializer         apps/students/serializers.py
 *   StudentRequirementSerializer
 *                             apps/student_requirement/serializers.py
 *
 * `match_percentage` and `best_matching_time` are annotated onto search
 * results ONLY when preferred_day + start + end + timezone are all supplied
 * together — hence optional. Everything the Match Card renders has to cope
 * with them being absent.
 */

export interface UserRef {
  id: string;
  email: string;
  full_name: string;
  first_name?: string;
  last_name?: string;
  role?: string;
}

export interface Named {
  id: string;
  name: string;
}

export interface TeacherRef {
  id: string;
  user: UserRef;
  profile_photo: string | null;
  bio: string | null;
  experience_years: number | null;
  qualification_level: string | null;
  qualification_detail: string | null;
}

export interface AvailabilitySlot {
  id: string;
  day_type: string;
  time_slot: string;
}

export type TeachingMode = "online" | "offline" | "both";

export interface TeacherProfile {
  id: string;
  teacher: TeacherRef;
  headline: string | null;
  teaching_mode: TeachingMode;
  hourly_rate: string | null;
  monthly_rate: string | null;
  monthly_rate_max: string | null;
  rating: string | null;
  verification_status: string;
  moderation_status: string;
  is_verified: boolean;
  is_fully_verified: boolean;
  years_of_experience: number | null;
  subjects: Named[];
  languages: Named[];
  cities: Named[];
  availability_slots: AvailabilitySlot[];
  created_at: string;
  updated_at: string;

  /** Present only when the search was given a full schedule window. */
  match_percentage?: number | null;
  best_matching_time?: string | null;
}

export interface WeeklyAvailabilitySlot {
  id: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
  timezone: string;
  is_active: boolean;
}

/** GET /search/teachers/{teacher_id}/ - a teacher's own public
 * marketplace profile, scoped to what "Learn with this teacher" needs. */
export interface PublicTeacherMarketplaceProfile {
  id: string;
  teacher_id: string;
  name: string;
  headline: string | null;
  teaching_mode: TeachingMode;
  rating: string | null;
  is_verified: boolean;
  years_of_experience: number | null;
  subjects: Named[];
  languages: Named[];
  weekly_availability: WeeklyAvailabilitySlot[];
}

export interface StudentProfile {
  id: string;
  user: UserRef;
  profile_photo: string | null;
  education_level: string | null;
  grade_or_year: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  pincode: string | null;
  country: string | null;
  preferred_subjects: string | null;
  bio: string | null;
}

export interface SchedulePreference {
  id: string;
  day_of_week: number;
  day_of_week_label?: string;
  start_time: string;
  end_time: string;
  timezone?: string;
  flexibility?: "flexible" | "fixed";
  priority?: string;
}

export interface StudentRequirement {
  id: string;
  student_name: string;
  subject: Named | null;
  student_class: string | null;
  /** Ranked most-to-least preferred - array order IS the rank. */
  preferred_languages: Named[];
  no_language_preference: boolean;
  budget_min: string | null;
  budget_max: string | null;
  teaching_mode: TeachingMode;
  city: Named | null;
  /** Set instead of `city` when the requirement was located via the
   *  pincode escape hatch (e.g. "743126") rather than picked from the
   *  city list - null whenever `city` is set. */
  pincode: string | null;
  preferred_timing: string | null;
  description: string | null;
  status: string;
  lead_distribution_status?: string | null;
  class_duration_minutes?: number | null;
  schedule_preferences?: SchedulePreference[];
  /** True once ANY teacher has unlocked this requirement's contact
   *  details - the real "can this still be edited" signal, independent
   *  of `status` (which flips to "matched" the moment a teacher is
   *  merely soft-matched, long before anyone unlocks anything). */
  has_unlocked_lead: boolean;
  created_at: string;
}

/* ---------------------------------------------------------------- *
 * Teacher side. Field names taken from live responses, not guessed.  *
 * ---------------------------------------------------------------- */

/** GET /dashboard/ — the teacher's own numbers. */
export interface TeacherDashboard {
  wallet_balance?: number | string | null;
  extra_unlocks?: number | null;
  free_leads_remaining?: number | null;
  allowance_total?: number | null;
  allowance_used?: number | null;
  allowance_resets_in_days?: number | null;
  allowance_resets_at?: string | null;
  todays_leads?: number | null;
  unlocked_leads?: number | null;
  pending_rating_count?: number | null;
  subscription_status?: string | null;
}

/** GET /subscriptions/quota/ */
export interface Quota {
  period_start?: string;
  period_end?: string;
  days_until_reset?: number;
  total_free_leads?: number;
  used_free_leads?: number;
  remaining_free_leads?: number;
  has_free_leads_remaining?: boolean;
}

/** GET /leads/ — a student lead matched to this teacher. */
export interface Lead {
  id: string;
  subject_name?: string | null;
  teaching_mode?: string | null;
  city_name?: string | null;
  budget_min?: string | null;
  budget_max?: string | null;
  student_name?: string | null;
  status?: string | null;
  is_viewed?: boolean;
  contact_unlocked?: boolean;
  my_rating?: string | null;
  /** How many teachers across the whole pool have unlocked this lead.
   *  Always null on a direct offer (is_direct_offer) - there is only ever
   *  one teacher, so the count would just be them counting themselves. */
  unlocked_count?: number | null;
  /** True when this teacher was picked directly ("Learn with this
   *  teacher") rather than matched into the general pool - rejecting has
   *  no "next teacher" to fall through to, unlike an ordinary lead. */
  is_direct_offer?: boolean;
  created_at: string;
  /** Only present once unlocked. */
  student_email?: string | null;
  student_mobile?: string | null;
  description?: string | null;
  preferred_timing?: string | null;
}

/** GET /matching/assignments/ — a time-limited offer of a lead. */
export interface Assignment {
  id: string;
  lead?: string | null;
  subject_name?: string | null;
  subscription_tier?: string | null;
  assignment_stage?: string | null;
  assigned_at?: string | null;
  expires_at?: string | null;
  status?: string | null;
  response?: string | null;
  time_match_score?: number | null;
  location_score?: number | null;
  subject_match_score?: number | null;
  language_match_score?: number | null;
}

/** GET /subscriptions/plans/ */
export interface Plan {
  id: string;
  name: string;
  monthly_price?: string | null;
  compare_at_price?: string | null;
  discount_percent?: number | null;
  free_leads?: number | null;
  base_leads?: number | null;
  bonus_leads?: number | null;
  priority_rank?: number | null;
  is_featured_listing?: boolean;
  status?: string | null;
}

/** GET /auth/staff/departments/ — where an approved admin is assigned. */
export interface AdminDepartment {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  admin_count: number;
  created_at: string;
  updated_at: string;
}

/**
 * GET /auth/staff/admin-account-requests/ — a self-service "become an
 * Admin" request. Distinct from the legacy AdminLoginRequest (a single
 * login attempt for an admin who already exists).
 */
export interface AdminAccountRequest {
  id: string;
  email: string;
  mobile: string;
  first_name: string;
  last_name: string;
  status: "pending" | "approved" | "denied";
  department: string | null;
  department_name: string | null;
  created_admin_account_name: string | null;
  reviewed_by_email: string | null;
  reviewed_at: string | null;
  deny_reason: string;
  requested_ip: string | null;
  requested_user_agent: string;
  created_at: string;
}

/**
 * GET/POST /subjects/ , GET/PUT/PATCH/DELETE /subjects/{id}/ — writes are
 * Super-Admin-only (apps/accounts/api_permissions.py); GET stays open to
 * every signed-in role (and the public registration form).
 */
export interface Subject {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  icon: string | null;
  is_active: boolean;
  is_skill_based: boolean;
  created_at: string;
  updated_at: string;
}

/** GET/POST /languages/ , GET/PUT/PATCH/DELETE /languages/{id}/ — same
 *  Super-Admin-only write rule as Subject. */
export interface Language {
  id: string;
  name: string;
  code: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** Embedded in fake-lead-report and lead-quality summary rows. */
export interface SanctionSummary {
  id: string;
  kind: string;
  source: string;
  is_automatic: boolean;
  reason: string;
  at: string;
}

/** The most recent "fake" rating that (re)triggered a student's review item. */
export interface LatestFakeReport {
  teacher_email: string;
  teacher_name: string;
  lead_id: string;
  subject: string;
  note: string;
  /** ISO timestamp - the field is named `at`, not `latest_report` itself. */
  at: string;
}

/** GET /ops/fake-lead-reports/ — students with open fake-lead review items. */
export interface FakeLeadReport {
  review_item_id: string;
  student_id: string | null;
  student_email: string;
  student_name: string;
  account_active: boolean | null;
  distinct_teachers_7d: number;
  distinct_teachers_30d: number;
  distinct_teachers_all: number;
  total_reports: number;
  latest_report: LatestFakeReport | null;
  auto_banned: boolean;
  sanction: SanctionSummary | null;
  priority: string;
  updated_at: string;
}

/** GET /ops/students-lead-quality/ (no params) — one row per student. */
export interface StudentLeadQualitySummary {
  student_id: string;
  student_email: string;
  student_name: string;
  account_active: boolean | null;
  total_ratings: number;
  genuine: number;
  unreachable: number;
  fake: number;
  sanction: SanctionSummary | null;
}

/** GET /ops/students-lead-quality/?student_id= — that student's ratings. */
export interface StudentLeadQualityRating {
  id: string;
  lead_id: string;
  teacher_id: string;
  teacher_name: string;
  teacher_email: string;
  verdict: "genuine" | "unreachable" | "fake";
  note: string;
  clawed_back: boolean;
  created_at: string;
}

/** GET /ops/teacher-lead-reviews/ */
export interface TeacherLeadReview {
  id: string;
  teacher_id: string;
  teacher_name: string;
  teacher_email: string;
  student_id: string;
  student_name: string;
  lead_id: string;
  verdict: "genuine" | "unreachable" | "fake";
  note: string;
  is_direct_offer: boolean;
  created_at: string;
}

/** GET /ops/events/ — one privileged/security-relevant action. */
export interface AuditLogEntry {
  id: string;
  created_at: string;
  actor: string | null;
  actor_email: string;
  actor_role: string;
  actor_name: string;
  category: string;
  action: string;
  status: "success" | "failure" | "pending";
  target_type: string;
  target_id: string | null;
  target_repr: string;
  message: string;
  metadata: Record<string, unknown>;
  ip_address: string | null;
  user_agent: string;
}

/** GET /admin/users/ , /admin/users/{id}/ — the platform user directory. */
export interface AdminUser {
  id: string;
  email: string;
  mobile: string;
  first_name: string;
  last_name: string;
  full_name: string;
  role: "student" | "teacher" | "admin" | "superadmin";
  is_active: boolean;
  is_staff: boolean;
  is_email_verified: boolean;
  is_mobile_verified: boolean;
  has_active_session: boolean;
  profile_type: "student" | "teacher" | null;
  last_login: string | null;
  created_at: string;
}

/**
 * GET /ops/sanctions/ — a ban or suspension on an account. `source` is
 * "manual" for a Super Admin action, or one of the auto_* values for a
 * system-triggered ban (fake-lead thresholds, staff-login brute force).
 */
export interface AccountSanction {
  id: string;
  user: string;
  user_email: string;
  user_name: string;
  user_role: string;
  user_active: boolean;
  kind: "ban" | "suspend";
  source: string;
  is_automatic: boolean;
  reason: string;
  created_by: string | null;
  created_by_email: string;
  review_item: string | null;
  payload: Record<string, unknown>;
  active: boolean;
  lifted_at: string | null;
  lifted_by_email: string;
  lift_reason: string;
  created_at: string;
}

/** GET /ops/overview/ — platform KPIs for the Super Admin dashboard. */
export interface OpsOverview {
  generated_at: string;
  users: {
    total: number;
    active: number;
    inactive: number;
    by_role: Record<string, number>;
    new_7d: number;
    new_30d: number;
  };
  taxonomy: { subjects: number; languages: number };
  pending_admin_logins: number;
  pending_admin_account_requests: number;
  security_events_7d: number;
  leads?: { total: number; new_7d: number };
  revenue?: { total: string; last_30d: string };
}

/**
 * What the sign-up flow parked in localStorage before the account existed.
 * Written by static/js/auth.js; read once here and then cleared.
 */
export interface Intent {
  role?: string;
  subject?: string | null;
  language?: string | null;
  level?: string | null;
  // Legacy shape - no longer written by static/js/auth.js's registerFlow,
  // but still read as a fallback for an already-saved intent from before
  // that changed, or an old bookmarked link: several days sharing one
  // time band.
  days?: number[];
  from?: string | null;
  to?: string | null;
  // Current shape: a list of distinct day+time windows, each with its
  // own time (Monday 7pm, Tuesday 8am, ...). Preferred over days/from/to
  // when present - see Discover.tsx's useInitialFilters and
  // replayIntent.ts's replayTeacherIntent (student and teacher sides,
  // respectively).
  windows?: { day: number; start: string; end: string }[];
  savedAt?: number;
}
