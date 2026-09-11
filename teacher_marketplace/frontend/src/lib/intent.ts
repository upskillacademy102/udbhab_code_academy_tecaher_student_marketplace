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
