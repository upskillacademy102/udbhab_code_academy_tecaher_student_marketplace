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
  created_at: string;
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
  days?: number[];
  from?: string | null;
  to?: string | null;
  savedAt?: number;
}
