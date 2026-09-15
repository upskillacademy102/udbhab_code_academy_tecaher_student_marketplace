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

export interface StudentProfile {
  id: string;
  user: UserRef;
  profile_photo: string | null;
  education_level: string | null;
  grade_or_year: string | null;
  city: string | null;
  state: string | null;
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
  preferred_language: Named | null;
  budget_min: string | null;
  budget_max: string | null;
  teaching_mode: TeachingMode;
  city: Named | null;
  preferred_timing: string | null;
  description: string | null;
  status: string;
  lead_distribution_status?: string | null;
  class_duration_minutes?: number | null;
  schedule_preferences?: SchedulePreference[];
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

/** GET /leads/ — a student enquiry matched to this teacher. */
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

/**
 * What the sign-up flow parked in localStorage before the account existed.
 * Written by static/js/auth.js; read once here and then cleared.
 */
export interface Intent {
  role?: string;
  subject?: string | null;
  language?: string | null;
  level?: string | null;
  // Legacy shape (still written by the pre-login sign-up flow in
  // static/js/auth.js): several days sharing one time band.
  days?: number[];
  from?: string | null;
  to?: string | null;
  // Current shape: a list of distinct day+time windows, each with its
  // own time (Monday 7pm, Tuesday 8am, ...). Preferred over days/from/to
  // when present - see Discover.tsx's useInitialFilters.
  windows?: { day: number; start: string; end: string }[];
  savedAt?: number;
}
