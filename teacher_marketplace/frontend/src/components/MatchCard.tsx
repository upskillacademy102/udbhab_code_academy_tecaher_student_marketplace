import { Link } from "react-router-dom";
import type { TeacherProfile } from "@/lib/types";

/**
 * The Match Card.
 *
 * Superprof's card is a photograph with data underneath. Almost no teacher
 * here has uploaded a photo, so copying that produces a grid of initials in
 * circles — a page that looks broken. So the hierarchy is inverted: the
 * card's anchor is the thing we compute and they can't, the schedule fit.
 *
 * Every card has a fit band, so every card has an anchor, and a missing photo
 * costs one 44px monogram instead of half the card.
 *
 * Three states:
 *   1. schedule known    -> teal fit band with the overlapping window
 *   2. no schedule       -> subject block, which doubles as the prompt to add
 *                           free hours (turning a data gap into the loop that
 *                           closes it)
 *   3. top result        -> a single marigold "Best match" ribbon, once per
 *                           grid, so the accent still means something
 */

const MONOGRAM_TONES = [
  "bg-pine-100 text-pine-800",
  "bg-marigold-100 text-marigold-800",
  "bg-ink-100 text-ink-700",
  "bg-pine-200 text-pine-900",
] as const;

/** Deterministic per-teacher tone, so a photoless grid looks varied and intentional. */
function toneFor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return MONOGRAM_TONES[h % MONOGRAM_TONES.length]!;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const first = parts[0]![0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]![0] ?? "") : "";
  return (first + last).toUpperCase();
}

function money(v: string | null): string | null {
  if (!v) return null;
  const n = Number(v);
  if (!Number.isFinite(n)) return null;
  return "₹" + Math.round(n).toLocaleString("en-IN");
}

function CheckSeal() {
  return (
    <svg className="h-[13px] w-[13px] shrink-0" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M8 1.5 9.9 3l2.4-.2.6 2.3 1.6 1.8-1.3 2 .2 2.4-2.3.6-1.8 1.6-2-1.3-2.4.2-.6-2.3L.7 8.3l1.3-2-.2-2.4 2.3-.6L5.9 1.7l2.1 1.3Z"
        fill="currentColor"
        opacity=".18"
      />
      <path d="m5.2 8.1 1.9 1.9 3.7-3.9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Star() {
  return (
    <svg className="h-3 w-3 shrink-0 text-marigold-500" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 1.6l1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.4l-3.8 2 .7-4.3-3.1-3 4.3-.6L8 1.6Z" fill="currentColor" />
    </svg>
  );
}

export interface MatchCardProps {
  teacher: TeacherProfile;
  /** Marks the single strongest result. Never more than one per grid. */
  isTopMatch?: boolean;
  /** Row index, used only to stagger the entry animation. */
  index?: number;
}

/**
 * A search row is a TeacherProfile, so `row.id` is the PROFILE id — but
 * /teachers/{id}/ is keyed on the Teacher id. Routing with the profile id
 * looks fine when clicked (the stash below hydrates the page) and then 404s
 * on refresh or a shared link, with the availability checker silently
 * failing too. So the route and the stash both key on the Teacher id.
 */
export function teacherRouteId(t: TeacherProfile): string {
  return t.teacher?.id ?? t.id;
}

/**
 * The detail page cannot refetch the marketplace half of a teacher — no API
 * returns another teacher's profile by id — so the card hands its own data
 * forward before navigating. Without this, opening a teacher shows the person
 * with no subjects, rate or rating.
 */
function stash(t: TeacherProfile) {
  try {
    sessionStorage.setItem("tp:" + teacherRouteId(t), JSON.stringify(t));
  } catch {
    /* private mode: the detail page degrades to the person record */
  }
}

export function MatchCard({ teacher, isTopMatch = false, index = 0 }: MatchCardProps) {
  const name = teacher.teacher?.user?.full_name || "Teacher";
  const photo = teacher.teacher?.profile_photo;
  const fit = teacher.match_percentage;
  const hasFit = typeof fit === "number" && Number.isFinite(fit);
  const rating = Number(teacher.rating ?? 0);
  const hasRating = rating > 0;
  const years = teacher.years_of_experience ?? teacher.teacher?.experience_years ?? null;
  const price = money(teacher.hourly_rate);
  const subjects = teacher.subjects?.map((s) => s.name) ?? [];
  const languages = teacher.languages?.map((l) => l.name) ?? [];

  return (
    <Link
      to={`/student/teachers/${teacherRouteId(teacher)}/`}
      onClick={() => stash(teacher)}
      className="u-stagger-item group flex h-full flex-col overflow-hidden rounded-2xl border-[1.5px] border-ink-300 bg-paper shadow-lift transition duration-150 ease-enter hover:-translate-y-px hover:border-pine-400 hover:shadow-raise"
      style={{ "--d": `${Math.min(index, 7) * 30}ms` } as React.CSSProperties}
    >
      {/* ---- The anchor: fit, or the subject fallback ---- */}
      {hasFit ? (
        <div className="relative border-b border-ink-200 bg-pine-50 px-4 py-3">
          {isTopMatch && (
            <span className="absolute right-3 top-3 rounded-full bg-marigold-500 px-2 py-0.5 text-[10.5px] font-bold uppercase tracking-wide text-ink-900">
              Best match
            </span>
          )}
          <p className="font-display text-[1.6rem] font-bold leading-none tracking-tight text-pine-800">
            {Math.round(fit as number)}%
            <span className="ml-1.5 font-sans text-[0.6875rem] font-semibold uppercase tracking-wider text-pine-600">
              fit
            </span>
          </p>
          <p className="mt-1 text-[0.75rem] font-medium text-pine-800">
            {teacher.best_matching_time || "Free when you are"}
          </p>
        </div>
      ) : (
        <div className="border-b border-ink-200 bg-paper-sunk px-4 py-3">
          <p className="font-display text-[1.1rem] font-semibold leading-tight text-ink-900">
            {subjects[0] ?? "Teacher"}
          </p>
          <p className="mt-0.5 text-[0.75rem] text-ink-500">Add your free hours to see fit</p>
        </div>
      )}

      {/* ---- Who ---- */}
      <div className="flex flex-1 flex-col gap-2.5 px-4 pt-3.5">
        <div className="flex items-center gap-3">
          {photo ? (
            <img src={photo} alt="" className="h-11 w-11 shrink-0 rounded-full object-cover" />
          ) : (
            <span
              className={`grid h-11 w-11 shrink-0 place-items-center rounded-full text-[0.8125rem] font-bold ${toneFor(teacher.id)}`}
              aria-hidden="true"
            >
              {initials(name)}
            </span>
          )}
          <div className="min-w-0">
            <p className="truncate text-[0.9375rem] font-semibold leading-tight text-ink-900">{name}</p>
            {teacher.is_fully_verified ? (
              <span className="mt-0.5 inline-flex items-center gap-1 text-[0.6875rem] font-medium text-pine-700">
                <CheckSeal /> ID &amp; qualifications checked
              </span>
            ) : teacher.is_verified ? (
              <span className="mt-0.5 inline-flex items-center gap-1 text-[0.6875rem] font-medium text-pine-700">
                <CheckSeal /> Verified
              </span>
            ) : null}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          {subjects.length > 0 && (
            <p className="truncate text-[0.8125rem] font-medium text-ink-800">
              {subjects.slice(0, 2).join(" · ")}
              {subjects.length > 2 && ` +${subjects.length - 2}`}
            </p>
          )}
          {languages.length > 0 && (
            <p className="truncate text-[0.75rem] text-ink-500">Teaches in {languages.slice(0, 3).join(", ")}</p>
          )}
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.75rem] text-ink-500">
            {hasRating ? (
              <span className="inline-flex items-center gap-1">
                <Star />
                <b className="font-semibold tabular-nums text-ink-900">{rating.toFixed(1)}</b>
              </span>
            ) : (
              <span className="rounded-full border border-ink-200 bg-paper-sunk px-2 py-px text-[0.6875rem] font-semibold uppercase tracking-wide text-ink-500">
                New
              </span>
            )}
            {years != null && <span>{years} yr{years === 1 ? "" : "s"} teaching</span>}
          </p>
        </div>
      </div>

      {/* ---- Price last: judged after the value is established ---- */}
      <div className="mt-3 flex items-center justify-between gap-2 border-t border-ink-200 px-4 py-3">
        <span className="text-[0.9375rem] font-bold tabular-nums text-ink-900">
          {price ?? "—"}
          {price && <span className="ml-0.5 text-[0.6875rem] font-medium text-ink-500">/hr</span>}
        </span>
        <span className="inline-flex items-center gap-1 text-[0.8125rem] font-semibold text-pine-700">
          See profile
          <span aria-hidden="true" className="transition group-hover:translate-x-0.5">→</span>
        </span>
      </div>
    </Link>
  );
}

/** Matches the card's real shape so nothing jumps when results land. */
export function MatchCardSkeleton() {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border-[1.5px] border-ink-200 bg-paper">
      <div className="h-[74px] border-b border-ink-200 bg-paper-sunk" />
      <div className="flex flex-1 flex-col gap-2.5 p-4">
        <div className="flex items-center gap-3">
          <div className="h-11 w-11 shrink-0 animate-pulse rounded-full bg-ink-100" />
          <div className="flex-1 space-y-1.5">
            <div className="h-3 w-2/3 animate-pulse rounded bg-ink-100" />
            <div className="h-2.5 w-1/2 animate-pulse rounded bg-ink-100" />
          </div>
        </div>
        <div className="h-2.5 w-3/4 animate-pulse rounded bg-ink-100" />
        <div className="h-2.5 w-1/2 animate-pulse rounded bg-ink-100" />
      </div>
      <div className="border-t border-ink-200 p-4">
        <div className="h-3 w-1/3 animate-pulse rounded bg-ink-100" />
      </div>
    </div>
  );
}
