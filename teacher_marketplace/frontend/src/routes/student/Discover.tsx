import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Named, TeacherProfile } from "@/lib/types";
import { clearIntent, formatWindows, readIntent, saveIntent, type TimeWindow } from "@/lib/intent";
import { MatchCard, MatchCardSkeleton } from "@/components/MatchCard";
import { WindowPicker } from "@/components/WindowPicker";

/**
 * Discover — the first screen after sign-up.
 *
 * What it replaces: "Complete your profile", "No requirements yet" and "No
 * recommendations yet", stacked. Three empty states on the highest-leverage
 * screen in the product.
 *
 * What it does instead: reads the answers the visitor gave BEFORE they had an
 * account (subject, language, free hours, parked in localStorage by the
 * sign-up flow) and turns them straight into a scored search. The payoff for
 * filling in the hero is that this page opens on real, ranked people.
 *
 * Low inventory is a designed state, not an accident. Under six results the
 * page stops pretending to be a catalogue and becomes request-first, because
 * a thin grid is just a prettier empty state.
 */

const LOW_INVENTORY = 6;

function useTaxonomy() {
  const subjects = useQuery({
    queryKey: ["subjects"],
    queryFn: () => api.list<Named>("/subjects/", { params: { is_active: "true" } }),
    staleTime: 10 * 60_000,
  });
  const languages = useQuery({
    queryKey: ["languages"],
    queryFn: () => api.list<Named>("/languages/", { params: { is_active: "true" } }),
    staleTime: 10 * 60_000,
  });
  return {
    subjects: subjects.data?.items ?? [],
    languages: languages.data?.items ?? [],
  };
}

interface Filters {
  subject: string | null;
  language: string | null;
  // A list of specific day+time windows (Monday 7-8pm, Tuesday 8-9am, ...)
  // rather than several days sharing one coarse band.
  windows: TimeWindow[];
  // "No fixed time — match me to whatever the teacher offers." Mutually
  // exclusive with windows: adding/editing one turns this off, turning
  // this on clears them. Same affordance as the "Find Verified Teachers"
  // filter page, for a student with no fixed schedule.
  flexible: boolean;
}

/**
 * Nobody fits what was just searched — carry it into "Post what you need"
 * rather than sending the student back to a blank form. Same localStorage
 * handoff the pre-login sign-up flow already uses; Requirements reads and
 * clears it once, on the way to opening the form pre-filled.
 */
function carryIntoRequirement(filters: Filters, hasSchedule: boolean): void {
  saveIntent({
    subject: filters.subject,
    language: filters.language,
    windows: hasSchedule ? filters.windows : [],
  });
}

function useInitialFilters(): Filters {
  return useMemo(() => {
    const intent = readIntent();
    // Read once, then clear — it must not resurrect on a later visit.
    if (intent) clearIntent();
    let windows: TimeWindow[] = [];
    if (intent?.windows?.length) {
      windows = intent.windows;
    } else if (Array.isArray(intent?.days) && intent.days.length && intent?.from && intent?.to) {
      // Legacy shape from the pre-login sign-up flow: several days sharing
      // one band. Expand into one window per day so it renders the same.
      windows = intent.days.map((d) => ({ day: d, start: intent!.from!, end: intent!.to! }));
    }
    return {
      subject: intent?.subject ?? null,
      language: intent?.language ?? null,
      windows,
      flexible: false,
    };
  }, []);
}

export function Discover() {
  const [filters, setFilters] = useState<Filters>(useInitialFilters());
  const [editing, setEditing] = useState(false);
  const { subjects, languages } = useTaxonomy();
  // "Something else" escape for both — the taxonomy is never the full set
  // of things a student might want to learn or the language they want it
  // in. Free text is resolved server-side by SubjectMatchingService /
  // LanguageMatchingService (exact/alias/fuzzy); nothing recognized just
  // means zero results here, same as any other filter combination with
  // no inventory yet.
  const [subjectMode, setSubjectMode] = useState<"select" | "custom">("select");
  const [languageMode, setLanguageMode] = useState<"select" | "custom">("select");

  const hasSchedule = !filters.flexible && filters.windows.length > 0;

  const params = useMemo(() => {
    const p: Record<string, string> = {};
    if (filters.subject) p.subject = filters.subject;
    if (filters.language) p.language = filters.language;
    if (hasSchedule) {
      p.preferred_slots = JSON.stringify(
        filters.windows.map((w) => ({ day: w.day, start_time: w.start, end_time: w.end }))
      );
      p.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
      p.duration_minutes = "60";
    }
    return p;
  }, [filters, hasSchedule]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["discover", params],
    queryFn: () => api.list<TeacherProfile>("/search/teachers/", { params }),
  });

  const results = data?.items ?? [];
  const lowInventory = !isLoading && !isError && results.length > 0 && results.length < LOW_INVENTORY;

  const setWindows = (windows: TimeWindow[]) => setFilters((f) => ({ ...f, windows, flexible: false }));
  const toggleFlexible = () => setFilters((f) => ({ ...f, flexible: !f.flexible, windows: [] }));

  const headline = (() => {
    if (isLoading) return "Finding your matches…";
    if (isError) return "We couldn't load your matches";
    if (!results.length) return "No teachers match that yet";
    const who = filters.subject ? `${filters.subject} teachers` : "teachers";
    if (hasSchedule) return `${results.length} ${who} free ${formatWindows(filters.windows)}`;
    return `${results.length} ${who} ready to help`;
  })();

  return (
    <div className="flex flex-col gap-6">
      {/* ---- What we matched on. Restates the goal and doubles as the control. ---- */}
      <section className="u-card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-200 px-5 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[0.75rem] font-semibold uppercase tracking-wider text-ink-500">Looking for</span>
            <Pill>{filters.subject ?? "Any subject"}</Pill>
            <Pill>{filters.language ?? "Any language"}</Pill>
            <Pill>{hasSchedule ? formatWindows(filters.windows) : filters.flexible ? "Flexible — any time works" : "Any time"}</Pill>
          </div>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => setEditing((v) => !v)}>
            {editing ? "Done" : "Change"}
          </button>
        </div>

        {editing && (
          <div className="flex flex-col gap-5 px-5 py-5">
            <div>
              <div className="flex items-baseline justify-between">
                <p className="u-eyebrow">Subject</p>
                <button type="button" className="u-link text-[0.75rem]"
                  onClick={() => {
                    setSubjectMode(subjectMode === "select" ? "custom" : "select");
                    setFilters((f) => ({ ...f, subject: null }));
                  }}>
                  {subjectMode === "select" ? "Don't see it? Type it in" : "Pick from list"}
                </button>
              </div>
              <div className="mt-2.5">
                {subjectMode === "select" ? (
                  <ChipRow
                    options={subjects.map((s) => s.name)}
                    value={filters.subject}
                    onPick={(v) => setFilters((f) => ({ ...f, subject: v }))}
                    emptyHint="No subjects have been added yet."
                  />
                ) : (
                  <input className="u-input" maxLength={60} placeholder="e.g. Tabla, French, NEET Biology"
                    value={filters.subject ?? ""}
                    onChange={(e) => setFilters((f) => ({ ...f, subject: e.target.value || null }))} />
                )}
              </div>
            </div>

            <div>
              <div className="flex items-baseline justify-between">
                <p className="u-eyebrow">Language</p>
                <button type="button" className="u-link text-[0.75rem]"
                  onClick={() => {
                    setLanguageMode(languageMode === "select" ? "custom" : "select");
                    setFilters((f) => ({ ...f, language: null }));
                  }}>
                  {languageMode === "select" ? "Type it in" : "Pick from list"}
                </button>
              </div>
              <div className="mt-2.5">
                {languageMode === "select" ? (
                  <ChipRow
                    options={languages.map((l) => l.name)}
                    value={filters.language}
                    onPick={(v) => setFilters((f) => ({ ...f, language: v }))}
                    emptyHint="No languages have been added yet."
                  />
                ) : (
                  <input className="u-input" maxLength={60} placeholder="e.g. Tulu, Sindhi, Sign Language"
                    value={filters.language ?? ""}
                    onChange={(e) => setFilters((f) => ({ ...f, language: e.target.value || null }))} />
                )}
              </div>
            </div>

            <div>
              <p className="u-eyebrow">When are you free?</p>
              <div className="mt-2.5">
                <WindowPicker windows={filters.windows} flexible={filters.flexible} onChange={setWindows} onToggleFlexible={toggleFlexible} />
              </div>
            </div>

            {!hasSchedule && !filters.flexible && (
              <p className="u-fine">
                Without any free hours we can't rank by who actually fits — you'll just see everyone.
              </p>
            )}
          </div>
        )}
      </section>

      {/* ---- The count, in the display face. The designed peak of the product. ---- */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="u-h2">{headline}</h1>
        {!isLoading && !isError && results.length > 0 && (
          <a href="/student/teachers/" className="u-link text-[0.875rem]">
            Search all teachers →
          </a>
        )}
      </div>

      {/* ---- States ---- */}
      {isLoading && (
        <div className="grid gap-5 grid-auto-fill-280">
          {Array.from({ length: 6 }).map((_, i) => (
            <MatchCardSkeleton key={i} />
          ))}
        </div>
      )}

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? "Something went wrong."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>
            Try again
          </button>
        </div>
      )}

      {!isLoading && !isError && results.length === 0 && (
        <NoResults subject={filters.subject} onPost={() => carryIntoRequirement(filters, hasSchedule)} />
      )}

      {!isLoading && !isError && results.length > 0 && (
        <>
          {lowInventory && (
            <LowInventoryNote count={results.length} onPost={() => carryIntoRequirement(filters, hasSchedule)} />
          )}
          <div className="grid gap-5 grid-auto-fill-280">
            {results.map((t, i) => (
              <MatchCard key={t.id} teacher={t} index={i} isTopMatch={i === 0 && hasSchedule} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-ink-300 bg-paper px-3 py-1 text-[0.8125rem] font-medium text-ink-800">
      {children}
    </span>
  );
}

/** Single-select chips: tapping the active one clears it. */
function ChipRow({
  options, value, onPick, emptyHint,
}: {
  options: string[];
  value: string | null;
  onPick: (v: string | null) => void;
  emptyHint?: string;
}) {
  if (!options.length) return <p className="u-fine">{emptyHint}</p>;
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => (
        <button key={o} type="button" className="u-chip u-chip-sm" aria-pressed={value === o}
          onClick={() => onPick(value === o ? null : o)}>
          {o}
        </button>
      ))}
    </div>
  );
}

/**
 * Under six results the page stops behaving like a catalogue. The honest
 * count is shown rather than hidden, and the action becomes posting a
 * requirement — which is how this marketplace actually works anyway.
 */
function LowInventoryNote({ count, onPost }: { count: number; onPost: () => void }) {
  return (
    <section className="u-card u-card-pad border-pine-300 bg-pine-50">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="max-w-prose">
          <h2 className="u-h3">
            {count === 1 ? "One teacher fits so far" : `Only ${count} teachers fit so far`}
          </h2>
          <p className="u-body mt-1.5 text-ink-600">
            We're still growing in your subject. Post what you need and we'll take it to teachers as they join —
            you'll hear from them directly.
          </p>
        </div>
        <a href="/student/requirements/" className="u-btn-primary shrink-0" onClick={onPost}>
          Post what you need
        </a>
      </div>
    </section>
  );
}

function NoResults({ subject, onPost }: { subject: string | null; onPost: () => void }) {
  return (
    <section className="u-card flex flex-col items-center gap-4 px-6 py-14 text-center">
      <span className="grid h-14 w-14 place-items-center rounded-2xl bg-pine-100 text-pine-700">
        <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
      </span>
      <div className="max-w-prose">
        <h2 className="u-h3">No {subject ? `${subject} ` : ""}teachers yet</h2>
        <p className="u-body mt-2 text-ink-600">
          Nobody matches that right now. Tell us what you need and we'll bring it to teachers as they join.
        </p>
      </div>
      <a href="/student/requirements/" className="u-btn-primary" onClick={onPost}>
        Post what you need
      </a>
    </section>
  );
}
