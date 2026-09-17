import { api } from "./api";
import type { Named } from "./types";
import { BANDS, readIntent, clearIntent } from "./intent";

/**
 * Apply what a teacher answered before their account existed.
 *
 * Sign-up asks for subjects, languages (ranked) and teaching hours, but at
 * that point there is no account to attach them to — and the taxonomy
 * endpoints are unreachable logged out, so the answers are stored as plain
 * names. This runs once on the teacher's first authenticated page load and
 * turns them into real rows.
 *
 * Order matters: POST /teachers/profile/ does Teacher.objects.get_or_create,
 * so it must run first — it is what brings the Teacher record into
 * existence. Availability rows attach to the profile it creates.
 *
 * Failure is deliberately quiet. The teacher can set all of this on their
 * profile and hours pages; an error toast about a replay they never asked
 * for would be noise on the very first screen they see.
 */
export async function replayTeacherIntent(): Promise<boolean> {
  const intent = readIntent();
  if (!intent || intent.role !== "teacher") return false;

  // Read once. Whether or not it works, it must not run again — a retry loop
  // on every dashboard visit would keep re-adding availability rows.
  clearIntent();

  const wantedLanguages: string[] = Array.isArray(
    (intent as { teachLanguages?: string[] }).teachLanguages,
  )
    ? (intent as { teachLanguages: string[] }).teachLanguages
    : [];
  const subject = intent.subject ?? null;
  // Current shape: the "teach-hours" step now writes the same windows[]
  // (each day with its own time) the student "when" step always has -
  // static/js/auth.js's registerFlow no longer writes the legacy
  // days/from/to (one shared band for every day) below, but an
  // already-saved intent from before that change, or an old bookmarked
  // link, may still only have it.
  const windows = Array.isArray(intent.windows) ? intent.windows : [];
  const days = Array.isArray(intent.days) ? intent.days : [];

  let touched = false;

  try {
    const payload: Record<string, unknown> = {};

    if (subject) {
      const subjects = await api.list<Named>("/subjects/", { params: { page_size: 300 }, silent: true });
      const hit = subjects.items.find((s) => s.name.toLowerCase() === subject.toLowerCase());
      if (hit) payload.subjects = [hit.id];
    }

    if (wantedLanguages.length) {
      const languages = await api.list<Named>("/languages/", { params: { page_size: 300 }, silent: true });
      const byName = new Map(languages.items.map((l) => [l.name.toLowerCase(), l.id]));
      // Preserve the teacher's ranking: map in their order, not the API's.
      const ids = wantedLanguages
        .map((n) => byName.get(n.toLowerCase()))
        .filter((x): x is string => Boolean(x));
      if (ids.length) payload.languages = ids;
    }

    if (Object.keys(payload).length) {
      await api.post("/teachers/profile/", payload, { silent: true });
      touched = true;
    }
  } catch {
    // Profile creation failed; availability has nothing to attach to.
    return touched;
  }

  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";

  if (windows.length) {
    for (const w of windows) {
      try {
        await api.post(
          "/teachers/profile/weekly-availability/",
          { day_of_week: Number(w.day), start_time: w.start, end_time: w.end, timezone },
          { silent: true },
        );
        touched = true;
      } catch {
        // A duplicate window is rejected by a unique constraint, which is
        // fine — the row already exists, which is the outcome we wanted.
      }
    }
  } else if (days.length) {
    // Legacy shape: every day shares the same one time range.
    const band = BANDS.find((b) => b.from === intent.from) ?? BANDS[2];
    for (const day of days) {
      try {
        await api.post(
          "/teachers/profile/weekly-availability/",
          { day_of_week: Number(day), start_time: band.from, end_time: band.to, timezone },
          { silent: true },
        );
        touched = true;
      } catch {
        // A duplicate window is rejected by a unique constraint, which is
        // fine — the row already exists, which is the outcome we wanted.
      }
    }
  }

  return touched;
}
