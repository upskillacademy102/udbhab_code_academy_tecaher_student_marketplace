import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TeacherProfile } from "@/lib/types";
import { BANDS, DAYS, bandFromTime, clearIntent, readIntent, scheduleText } from "@/lib/intent";
import { MatchCard, MatchCardSkeleton } from "@/components/MatchCard";

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

interface Filters {
  subject: string | null;
  language: string | null;
  days: number[];
  band: string;
}

function useInitialFilters(): Filters {
  return useMemo(() => {
    const intent = readIntent();
    // Read once, then clear — it must not resurrect on a later visit.
    if (intent) clearIntent();
    return {
      subject: intent?.subject ?? null,
      language: intent?.language ?? null,
      days: Array.isArray(intent?.days) ? intent!.days! : [],
      band: bandFromTime(intent?.from),
    };
  }, []);
}

export function Discover() {
  const [filters, setFilters] = useState<Filters>(useInitialFilters());
  const [editing, setEditing] = useState(false);

  const band = BANDS.find((b) => b.id === filters.band) ?? BANDS[2];
  const hasSchedule = filters.days.length > 0;

  const params = useMemo(() => {
    const p: Record<string, string> = {};
    if (filters.subject) p.subject = filters.subject;
    if (filters.language) p.language = filters.language;
    // The API only scores when day + start + end + timezone arrive together.
    // It takes one day per call, so the first selected day drives the score.
    if (hasSchedule) {
      p.preferred_day = String(filters.days[0]);
      p.preferred_start_time = band.from;
      p.preferred_end_time = band.to;
      p.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
      p.duration_minutes = "60";
    }
    return p;
  }, [filters, band, hasSchedule]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["discover", params],
    queryFn: () => api.list<TeacherProfile>("/search/teachers/", { params }),
  });

  const results = data?.items ?? [];
  const lowInventory = !isLoading && !isError && results.length > 0 && results.length < LOW_INVENTORY;

  function toggleDay(n: number) {
    setFilters((f) => ({
      ...f,
      days: f.days.includes(n) ? f.days.filter((d) => d !== n) : [...f.days, n].sort((a, b) => a - b),
    }));
  }

  const headline = (() => {
    if (isLoading) return "Finding your matches…";
    if (isError) return "We couldn't load your matches";
    if (!results.length) return "No teachers match that yet";
    const who = filters.subject ? `${filters.subject} teachers` : "teachers";
    if (hasSchedule) return `${results.length} ${who} free ${scheduleText(filters.days, filters.band)}`;
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
            <Pill>{hasSchedule ? scheduleText(filters.days, filters.band) : "Any time"}</Pill>
          </div>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => setEditing((v) => !v)}>
            {editing ? "Done" : "Change"}
          </button>
        </div>

        {editing && (
          <div className="flex flex-col gap-5 px-5 py-5">
            <div>
              <p className="u-eyebrow">Days you're free</p>
              <div className="mt-2.5 grid grid-cols-7 gap-1.5 sm:max-w-sm">
                {DAYS.map((d) => (
                  <button
                    key={d.n}
                    type="button"
                    aria-pressed={filters.days.includes(d.n)}
                    aria-label={d.full}
                    onClick={() => toggleDay(d.n)}
                    className={
                      "flex h-11 items-center justify-center rounded-lg border-[1.5px] text-[0.8125rem] font-semibold transition duration-150 ease-enter " +
                      (filters.days.includes(d.n)
                        ? "border-pine-600 bg-pine-600 text-white"
                        : "border-ink-300 bg-paper text-ink-600 hover:border-pine-400 hover:bg-pine-50")
                    }
                  >
                    {d.s}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <p className="u-eyebrow">Time of day</p>
              <div className="mt-2.5 grid grid-cols-3 gap-2 sm:max-w-sm">
                {BANDS.map((b) => (
                  <button
                    key={b.id}
                    type="button"
                    aria-pressed={filters.band === b.id}
                    onClick={() => setFilters((f) => ({ ...f, band: b.id }))}
                    className="u-chip flex-col gap-0.5 px-2 py-2"
                  >
                    <span className="text-[0.875rem]">{b.label}</span>
                    <span className="text-[0.6875rem] font-normal tabular-nums text-ink-400">{b.hint}</span>
                  </button>
                ))}
              </div>
            </div>

            {!hasSchedule && (
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

      {!isLoading && !isError && results.length === 0 && <NoResults subject={filters.subject} />}

      {!isLoading && !isError && results.length > 0 && (
        <>
          {lowInventory && <LowInventoryNote count={results.length} />}
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

/**
 * Under six results the page stops behaving like a catalogue. The honest
 * count is shown rather than hidden, and the action becomes posting a
 * requirement — which is how this marketplace actually works anyway.
 */
function LowInventoryNote({ count }: { count: number }) {
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
        <a href="/student/requirements/" className="u-btn-primary shrink-0">
          Post what you need
        </a>
      </div>
    </section>
  );
}

function NoResults({ subject }: { subject: string | null }) {
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
      <a href="/student/requirements/" className="u-btn-primary">
        Post what you need
      </a>
    </section>
  );
}
