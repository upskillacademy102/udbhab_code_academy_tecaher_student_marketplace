/**
 * The answers the visitor gave before they had an account.
 *
 * static/js/auth.js writes this to localStorage at the moment registration
 * succeeds, because registration redirects through /login/ and the user may
 * open that in a new tab. Discover reads it once on first load, uses it to
 * seed the search, and clears it so it never resurrects on a later visit.
 */
import type { Intent } from "./types";

const KEY = "udbhab:intent";
const TTL_MS = 24 * 60 * 60 * 1000;

export function readIntent(): Intent | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as Intent;
    if (!v?.savedAt || Date.now() - v.savedAt > TTL_MS) {
      localStorage.removeItem(KEY);
      return null;
    }
    return v;
  } catch {
    // Private mode, storage disabled, or corrupt JSON. Discover just opens
    // unfiltered — worse, but never broken.
    return null;
  }
}

export function clearIntent(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* nothing to do */
  }
}

/**
 * Carry a search forward into "Post what you need" so a student who just
 * typed a subject/language/schedule into Discover and found nobody isn't
 * asked to type the same thing again a screen later. Same storage key and
 * shape auth.js writes pre-login — Requirements reads and clears it once,
 * the same way Discover already does.
 */
export function saveIntent(partial: Omit<Intent, "savedAt">): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...partial, savedAt: Date.now() }));
  } catch {
    /* private mode / storage disabled - the click still navigates */
  }
}

/** The three time bands the landing page and sign-up offer. */
export const BANDS = [
  { id: "morning", label: "Morning", hint: "6–12", from: "06:00", to: "12:00" },
  { id: "afternoon", label: "Afternoon", hint: "12–5", from: "12:00", to: "17:00" },
  { id: "evening", label: "Evening", hint: "5–10", from: "17:00", to: "22:00" },
] as const;

export const DAYS = [
  { n: 1, s: "M", full: "Monday" },
  { n: 2, s: "T", full: "Tuesday" },
  { n: 3, s: "W", full: "Wednesday" },
  { n: 4, s: "T", full: "Thursday" },
  { n: 5, s: "F", full: "Friday" },
  { n: 6, s: "S", full: "Saturday" },
  { n: 7, s: "S", full: "Sunday" },
] as const;

/**
 * "Monday mornings", "Tuesday & Thursday evenings", "most evenings" — the day
 * stays singular and the part of day takes the plural, which is how people
 * actually say it.
 */
export function scheduleText(days: number[], bandId: string): string {
  // DAYS is `as const`, so `full` is a literal union rather than plain
  // string — the predicate has to keep that type, not widen it.
  const names = days
    .map((n) => DAYS.find((d) => d.n === n)?.full)
    .filter((x): x is NonNullable<typeof x> => Boolean(x));
  const band = (BANDS.find((b) => b.id === bandId)?.label ?? "").toLowerCase();
  if (!names.length) return "";
  if (names.length >= 5) return `most ${band}s`;
  let dayText: string;
  if (names.length === 1) dayText = names[0]!;
  else if (names.length === 2) dayText = `${names[0]} & ${names[1]}`;
  else dayText = `${names.slice(0, -1).join(", ")} & ${names[names.length - 1]}`;
  return `${dayText} ${band}s`;
}

/** Which band a stored "from" time belongs to. */
export function bandFromTime(from?: string | null): string {
  return BANDS.find((b) => b.from === from)?.id ?? "evening";
}

/**
 * One specific day + time range — "Monday 7-8pm" as its own thing,
 * distinct from "Tuesday 8-9am", rather than several days sharing one
 * coarse band. A student picks a list of these instead of days[] + a
 * single shared band when their free time genuinely varies by day.
 */
export interface TimeWindow {
  day: number;
  start: string;
  end: string;
}

export const blankTimeWindow = (): TimeWindow => ({ day: 1, start: "18:00", end: "19:00" });

function formatClock(hhmm: string): string {
  const parts = hhmm.split(":").map(Number);
  const h = parts[0] ?? NaN;
  const m = parts[1] ?? NaN;
  if (Number.isNaN(h) || Number.isNaN(m)) return hhmm;
  const period = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m === 0 ? `${h12} ${period}` : `${h12}:${String(m).padStart(2, "0")} ${period}`;
}

/** "Mon 7 PM, Tue 8 AM" — compact, for active-filter chips and summary pills. */
export function formatWindows(windows: TimeWindow[]): string {
  return windows
    .map((w) => {
      const day = DAYS.find((d) => d.n === w.day);
      return `${day ? day.full.slice(0, 3) : "?"} ${formatClock(w.start)}`;
    })
    .join(", ");
}
