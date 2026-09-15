import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Named, TeacherProfile } from "@/lib/types";
import { formatWindows, type TimeWindow } from "@/lib/intent";
import { MatchCard, MatchCardSkeleton } from "@/components/MatchCard";
import { FilterChips, type ActiveFilter } from "@/components/FilterChips";
import { WindowPicker } from "@/components/WindowPicker";

/**
 * Find teachers — the full search surface.
 *
 * Discover answers "who fits what I already told you". This answers "let me
 * look properly", so every filter the API supports is reachable, but the
 * active ones stay visible as removable chips rather than hiding inside a
 * panel. Invisible filter state is the main reason marketplace search feels
 * broken: three results, and no memory of why.
 *
 * Subject and language options come from the API here rather than being
 * rendered by Django: behind the login /subjects/ and /languages/ are
 * reachable, unlike on the public pages.
 */

const PRICE_BANDS = [
  { id: "u500", label: "Under ₹500", min: undefined, max: "500" },
  { id: "500-1000", label: "₹500–1,000", min: "500", max: "1000" },
  { id: "1000-2000", label: "₹1,000–2,000", min: "1000", max: "2000" },
  { id: "2000+", label: "₹2,000+", min: "2000", max: undefined },
] as const;

const MODES = [
  { id: "online", label: "Online" },
  { id: "offline", label: "In person" },
  { id: "both", label: "Either" },
] as const;

const SORTS = [
  { id: "", label: "Best match" },
  { id: "-rating", label: "Highest rated" },
  { id: "-experience", label: "Most experienced" },
  { id: "price", label: "Price: low to high" },
  { id: "-price", label: "Price: high to low" },
  { id: "newest", label: "Newest" },
] as const;

interface State {
  subject: string | null;
  language: string | null;
  mode: string | null;
  price: string | null;
  minRating: boolean;
  verifiedOnly: boolean;
  // A list of specific day+time windows (Monday 7-8pm, Tuesday 8-9am, ...)
  // rather than several days sharing one coarse band — a student free at
  // different times on different days needs each expressed separately.
  windows: TimeWindow[];
  // "I don't have a fixed time — match me to whatever the teacher offers."
  // Mutually exclusive with windows: adding/editing a window turns this
  // off, turning this on clears them. Without it, a student with no fixed
  // schedule has no way to say so — an empty windows list looks like an
  // unfinished filter rather than a deliberate "any time works" choice.
  flexible: boolean;
  sort: string;
}

const EMPTY: State = {
  subject: null, language: null, mode: null, price: null,
  minRating: false, verifiedOnly: false, windows: [], flexible: false, sort: "",
};

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

export function Search() {
  const [s, setS] = useState<State>(EMPTY);
  const [panelOpen, setPanelOpen] = useState(false);
  const { subjects, languages } = useTaxonomy();

  const hasSchedule = !s.flexible && s.windows.length > 0;
  const priceBand = PRICE_BANDS.find((p) => p.id === s.price);

  const params = useMemo(() => {
    const p: Record<string, string> = {};
    if (s.subject) p.subject = s.subject;
    if (s.language) p.language = s.language;
    if (s.mode) p.teaching_mode = s.mode;
    if (priceBand?.min) p.min_price = priceBand.min;
    if (priceBand?.max) p.max_price = priceBand.max;
    if (s.minRating) p.min_rating = "4";
    if (s.verifiedOnly) p.verified_only = "true";
    if (s.sort) p.ordering = s.sort;
    if (hasSchedule) {
      p.preferred_slots = JSON.stringify(
        s.windows.map((w) => ({ day: w.day, start_time: w.start, end_time: w.end }))
      );
      p.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
      p.duration_minutes = "60";
    }
    return p;
  }, [s, hasSchedule, priceBand]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["search", params],
    queryFn: () => api.list<TeacherProfile>("/search/teachers/", { params }),
  });

  const results = data?.items ?? [];
  const set = <K extends keyof State>(k: K, v: State[K]) => setS((p) => ({ ...p, [k]: v }));
  const setWindows = (windows: TimeWindow[]) => setS((p) => ({ ...p, windows, flexible: false }));
  const toggleFlexible = () => setS((p) => ({ ...p, flexible: !p.flexible, windows: [] }));

  const active: ActiveFilter[] = [];
  if (s.subject) active.push({ key: "subject", label: s.subject, onClear: () => set("subject", null) });
  if (s.language) active.push({ key: "language", label: `in ${s.language}`, onClear: () => set("language", null) });
  if (s.mode) active.push({ key: "mode", label: MODES.find((m) => m.id === s.mode)!.label, onClear: () => set("mode", null) });
  if (priceBand) active.push({ key: "price", label: priceBand.label, onClear: () => set("price", null) });
  if (s.minRating) active.push({ key: "rating", label: "4★ and up", onClear: () => set("minRating", false) });
  if (s.verifiedOnly) active.push({ key: "verified", label: "Verified only", onClear: () => set("verifiedOnly", false) });
  if (hasSchedule) active.push({ key: "when", label: formatWindows(s.windows), onClear: () => set("windows", []) });
  if (s.flexible) active.push({ key: "flexible", label: "Flexible — any time works", onClear: () => set("flexible", false) });

  return (
    <div className="flex flex-col gap-5">
      {/* ---- Controls ---- */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" className="u-btn-secondary" onClick={() => setPanelOpen((v) => !v)} aria-expanded={panelOpen}>
          <svg className="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 5h16l-6 8v6l-4-2v-4Z" />
          </svg>
          {panelOpen ? "Hide filters" : "Filters"}
          {active.length > 0 && (
            <span className="ml-0.5 grid h-5 min-w-5 place-items-center rounded-full bg-pine-700 px-1 text-[11px] font-bold text-white">
              {active.length}
            </span>
          )}
        </button>

        <label className="flex items-center gap-2 text-[0.875rem] text-ink-600">
          Sort
          <select className="u-select w-auto min-h-[40px] py-1.5" value={s.sort} onChange={(e) => set("sort", e.target.value)}>
            {SORTS.map((o) => (
              <option key={o.id} value={o.id}>{o.label}</option>
            ))}
          </select>
        </label>
      </div>

      {panelOpen && (
        <section className="u-card u-card-pad flex flex-col gap-6">
          <Group label="Subject">
            <ChipRow
              options={subjects.map((x) => x.name)}
              value={s.subject}
              onPick={(v) => set("subject", v)}
              emptyHint="No subjects have been added yet."
            />
          </Group>

          <Group label="Language">
            <ChipRow
              options={languages.map((x) => x.name)}
              value={s.language}
              onPick={(v) => set("language", v)}
              emptyHint="No languages have been added yet."
            />
          </Group>

          <Group label="How you'd like to learn">
            <ChipRow options={MODES.map((m) => m.label)} value={MODES.find((m) => m.id === s.mode)?.label ?? null}
              onPick={(label) => set("mode", label ? (MODES.find((m) => m.label === label)?.id ?? null) : null)} />
          </Group>

          <Group label="Price per hour">
            <ChipRow options={PRICE_BANDS.map((p) => p.label)} value={priceBand?.label ?? null}
              onPick={(label) => set("price", label ? (PRICE_BANDS.find((p) => p.label === label)?.id ?? null) : null)} />
          </Group>

          <Group label="When you're free">
            <WindowPicker windows={s.windows} flexible={s.flexible} onChange={setWindows} onToggleFlexible={toggleFlexible} />
          </Group>

          <Group label="Only show">
            <div className="flex flex-wrap gap-2">
              <button type="button" className="u-chip u-chip-sm" aria-pressed={s.verifiedOnly}
                onClick={() => set("verifiedOnly", !s.verifiedOnly)}>Verified teachers</button>
              <button type="button" className="u-chip u-chip-sm" aria-pressed={s.minRating}
                onClick={() => set("minRating", !s.minRating)}>Rated 4★ and up</button>
            </div>
          </Group>
        </section>
      )}

      <FilterChips filters={active} onClearAll={() => setS({ ...EMPTY, sort: s.sort })} />

      <h1 className="u-h2">
        {isLoading ? "Searching…" : isError ? "Couldn't load teachers" : results.length === 0 ? "Nothing matches that" : `${results.length} teacher${results.length === 1 ? "" : "s"}`}
      </h1>

      {isLoading && (
        <div className="grid gap-5 grid-auto-fill-280">
          {Array.from({ length: 6 }).map((_, i) => <MatchCardSkeleton key={i} />)}
        </div>
      )}

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? "Something went wrong."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {!isLoading && !isError && results.length === 0 && (
        <section className="u-card flex flex-col items-center gap-4 px-6 py-14 text-center">
          <h2 className="u-h3">No teachers match those filters</h2>
          <p className="u-body max-w-prose text-ink-600">
            Try removing one — the fewer things you ask for at once, the more people we can show you.
          </p>
          {active.length > 0 && (
            <button type="button" className="u-btn-primary" onClick={() => setS({ ...EMPTY, sort: s.sort })}>
              Clear filters
            </button>
          )}
        </section>
      )}

      {!isLoading && !isError && results.length > 0 && (
        <div className="grid gap-5 grid-auto-fill-280">
          {results.map((t, i) => (
            <MatchCard key={t.id} teacher={t} index={i} isTopMatch={i === 0 && hasSchedule && !s.sort} />
          ))}
        </div>
      )}
    </div>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="u-eyebrow">{label}</p>
      <div className="mt-2.5">{children}</div>
    </div>
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
