import { memo, useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { Named, StudentRequirement } from "@/lib/types";
import { DAYS } from "@/lib/intent";
import { toast } from "@/lib/ui";
import { TaxonomyCombobox } from "@/components/TaxonomyCombobox";

// Matches apps.student_requirement.models.MAX_PREFERRED_LANGUAGES.
const MAX_PREFERRED_LANGUAGES = 5;

/**
 * The "What do you need?" form — shared between posting a new requirement
 * (Requirements.tsx) and editing an existing open one (RequirementDetail.tsx).
 * Same fields, same validation, same free-text subject/language escape;
 * only the submit target and a couple of labels differ.
 */

const TZ = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
  } catch {
    return "Asia/Kolkata";
  }
})();

export interface Window_ {
  day_of_week: number;
  start_time: string;
  end_time: string;
  flexibility: "flexible" | "fixed";
}

export interface Draft {
  subject: string;
  student_class: string;
  // Ranked most-to-least preferred - array order IS the rank. Mandatory:
  // either this has at least one entry, or no_language_preference is true,
  // never neither (mirrors windows/flexible below).
  preferred_languages: string[];
  no_language_preference: boolean;
  teaching_mode: "online" | "offline" | "both";
  city: string;
  budget_min: string;
  budget_max: string;
  class_duration_minutes: number;
  preferred_timing: string;
  description: string;
  windows: Window_[];
}

export const blankWindow = (): Window_ => ({ day_of_week: 1, start_time: "18:00", end_time: "19:00", flexibility: "flexible" });

export const blankDraft = (): Draft => ({
  subject: "", student_class: "", preferred_languages: [], no_language_preference: false,
  teaching_mode: "online", city: "",
  budget_min: "", budget_max: "", class_duration_minutes: 60,
  preferred_timing: "", description: "", windows: [blankWindow()],
});

/** Flatten an existing (nested, read-shape) requirement into an editable Draft. */
export function draftFromRequirement(r: StudentRequirement): Draft {
  return {
    subject: r.subject?.name ?? "",
    student_class: r.student_class ?? "",
    preferred_languages: r.preferred_languages?.map((l) => l.name) ?? [],
    no_language_preference: r.no_language_preference ?? false,
    teaching_mode: r.teaching_mode,
    city: r.city?.name ?? "",
    budget_min: r.budget_min ?? "",
    budget_max: r.budget_max ?? "",
    class_duration_minutes: r.class_duration_minutes ?? 60,
    preferred_timing: r.preferred_timing ?? "",
    description: r.description ?? "",
    windows: r.schedule_preferences?.length
      ? r.schedule_preferences.map((w) => ({
          day_of_week: w.day_of_week,
          start_time: w.start_time.slice(0, 5),
          end_time: w.end_time.slice(0, 5),
          flexibility: w.flexibility ?? "flexible",
        }))
      : [blankWindow()],
  };
}

function useOptions() {
  const q = (key: string, path: string, pageSize: number) =>
    useQuery({
      queryKey: [key],
      queryFn: () => api.list<Named>(path, { params: { page_size: pageSize } }),
      staleTime: 10 * 60_000,
    });
  return {
    subjects: q("subjects", "/subjects/", 200).data?.items ?? [],
    languages: q("languages", "/languages/", 200).data?.items ?? [],
    grades: q("grade-levels", "/grade-levels/", 100).data?.items ?? [],
    cities: q("cities", "/location/cities/", 500).data?.items ?? [],
  };
}

export function RequirementForm({
  onClose, onSaved, initial, requirementId,
}: {
  onClose: () => void;
  /** For a new (non-editing) post, receives its teaching_mode - lets the
   * caller show an offline-specific "this takes longer" notice. */
  onSaved: (createdMode?: Draft["teaching_mode"]) => void;
  initial?: Partial<Draft> | null;
  /** Present -> PATCH this existing requirement instead of POSTing a new one. */
  requirementId?: string;
}) {
  const editing = Boolean(requirementId);
  const { subjects, languages, grades, cities } = useOptions();
  const [d, setD] = useState<Draft>(() => ({ ...blankDraft(), ...initial }));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [nonField, setNonField] = useState("");
  const [saving, setSaving] = useState(false);
  const [cityMode, setCityMode] = useState<"select" | "pincode">("select");
  // Subject is free text server-side (validate_subject resolves or, for a
  // genuinely new one, creates it) - the select is just the fast path for
  // what's already in the taxonomy. "Something else" switches to typing it
  // in, same escape hatch as the pre-login sign-up flow. A subject carried
  // in from a Discover search that came up empty (or from an existing
  // requirement being edited) starts in "custom" too - it's already known
  // text, not something that needs re-picking from a dropdown to match.
  const [subjectMode, setSubjectMode] = useState<"select" | "custom">(initial?.subject ? "custom" : "select");
  // Same free-text escape, applied per-item to the language ADD step (see
  // LanguageRankPicker) rather than to the whole field, since it's now a
  // ranked list.
  const [languageAddMode, setLanguageAddMode] = useState<"select" | "custom">("select");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Stable across renders (useCallback, not a plain inline function) so a
  // memoized child - e.g. the subject/city <select> option lists, which can
  // run into the hundreds of entries - can skip re-rendering when an
  // unrelated field (like this textarea) changes on every keystroke.
  const set = useCallback(<K extends keyof Draft>(k: K, v: Draft[K]) => {
    setD((p) => ({ ...p, [k]: v }));
    setErrors((e) => {
      if (!(k in e)) return e;
      const { [k as string]: _drop, ...rest } = e;
      return rest;
    });
  }, []);

  // Stable wrappers for the memoized NamedSelects - each depends only on
  // `set` (itself stable), so typing in an unrelated field never invalidates
  // them.
  const setSubject = useCallback((v: string | null) => set("subject", v ?? ""), [set]);
  const setGrade = useCallback((v: string) => set("student_class", v), [set]);
  const setCity = useCallback((v: string) => set("city", v), [set]);

  const setWindow = (i: number, patch: Partial<Window_>) =>
    setD((p) => ({ ...p, windows: p.windows.map((w, j) => (j === i ? { ...w, ...patch } : w)) }));

  const setLanguages = (preferred_languages: string[]) =>
    setD((p) => ({ ...p, preferred_languages, no_language_preference: false }));
  const toggleNoLanguagePreference = () =>
    setD((p) => ({ ...p, no_language_preference: !p.no_language_preference, preferred_languages: [] }));

  function validate(): boolean {
    const next: Record<string, string> = {};
    if (!d.subject) next.subject = "Pick a subject.";
    if (!d.no_language_preference && d.preferred_languages.length === 0) {
      next.language = 'Pick at least one language, or choose "Any language".';
    }
    if (d.teaching_mode !== "online" && !d.city) next.city = "We need a city for in-person lessons.";
    const rows = d.windows.filter((w) => w.start_time && w.end_time);
    if (!rows.length) next.schedule = "Add at least one time you're free.";
    else if (rows.some((w) => w.start_time >= w.end_time)) next.schedule = "Each slot needs to end after it starts.";
    if (d.budget_min && d.budget_max && Number(d.budget_min) > Number(d.budget_max)) {
      next.budget_min = "The minimum is above the maximum.";
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setNonField("");
    if (!validate()) return;
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        subject: d.subject,
        teaching_mode: d.teaching_mode,
        class_duration_minutes: d.class_duration_minutes,
        // Mandatory, unlike the optional fields below - always sent, never
        // gated on "was it filled in".
        preferred_languages: d.no_language_preference ? [] : d.preferred_languages,
        no_language_preference: d.no_language_preference,
        schedule_preferences: d.windows
          .filter((w) => w.start_time && w.end_time)
          .map((w) => ({
            day_of_week: Number(w.day_of_week),
            start_time: w.start_time,
            end_time: w.end_time,
            timezone: TZ,
            flexibility: w.flexibility,
          })),
      };
      // Only send what was filled in — blank strings are not "no preference"
      // to DRF, they're invalid values.
      for (const k of ["student_class", "city", "preferred_timing", "description"] as const) {
        if (d[k]) payload[k] = d[k];
      }
      for (const k of ["budget_min", "budget_max"] as const) {
        if (d[k]) payload[k] = Number(d[k]);
      }

      if (editing) {
        await api.patch(`/student-requirements/${requirementId}/`, payload, { silent: true });
        toast("success", "Saved.");
        onSaved();
      } else {
        await api.post("/student-requirements/", payload, { silent: true });
        toast("success", "Posted. We're matching you with teachers now.");
        onSaved(d.teaching_mode);
      }
    } catch (err) {
      const e2 = err as ApiError;
      if (e2.fieldErrors) setErrors(e2.fieldErrors);
      else setNonField(e2.message || (editing ? "Couldn't save that." : "Couldn't post that."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={editing ? "Edit your request" : "Post what you need"}>
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l border-ink-300 bg-paper shadow-raise">
        <header className="flex items-center justify-between gap-3 border-b border-ink-200 px-5 py-4">
          <h2 className="u-h3">{editing ? "Edit your request" : "What do you need?"}</h2>
          <button type="button" className="u-btn-ghost u-btn-sm" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <form className="flex flex-1 flex-col gap-4 overflow-y-auto p-5" onSubmit={save}>
          {nonField && <div className="u-alert u-alert-error">{nonField}</div>}

          <Field label="Subject" required error={errors.subject} htmlFor="rq-subject"
            action={
              <button type="button" className="u-link text-[0.75rem]"
                onClick={() => { setSubjectMode(subjectMode === "select" ? "custom" : "select"); set("subject", ""); }}>
                {subjectMode === "select" ? "Don't see it? Type it in" : "Pick from list"}
              </button>
            }>
            {subjectMode === "select" ? (
              <TaxonomyCombobox id="rq-subject" items={subjects.map((s) => s.name)} value={d.subject || null}
                onChange={setSubject} placeholder="Search subjects — e.g. Mathematics"
                emptyHint="No subjects have been added yet." />
            ) : (
              <input id="rq-subject" className="u-input" maxLength={60} placeholder="e.g. Tabla, French, NEET Biology"
                value={d.subject} onChange={(e) => set("subject", e.target.value)} />
            )}
          </Field>

          <Field label="Level" htmlFor="rq-class">
            <NamedSelect id="rq-class" value={d.student_class} onChange={setGrade} items={grades} placeholder="Any" />
          </Field>

          <Field label="Language" required error={errors.language}>
            <p className="u-hint -mt-1 mb-2">
              Rank every language you'd accept, most preferred first — the more you add, the more teachers can reach you.
            </p>
            <LanguageRankPicker
              languages={d.preferred_languages}
              allLanguages={languages}
              noPreference={d.no_language_preference}
              onChange={setLanguages}
              onToggleNoPreference={toggleNoLanguagePreference}
              addMode={languageAddMode}
              onToggleAddMode={() => setLanguageAddMode((m) => (m === "select" ? "custom" : "select"))}
            />
          </Field>

          <Field label="How" required>
            <div className="flex gap-2">
              {(["online", "offline", "both"] as const).map((m) => (
                <button key={m} type="button" className="u-chip u-chip-sm flex-1" aria-pressed={d.teaching_mode === m}
                  onClick={() => set("teaching_mode", m)}>
                  {m === "online" ? "Online" : m === "offline" ? "In person" : "Either"}
                </button>
              ))}
            </div>
          </Field>

          {d.teaching_mode !== "online" && (
            <Field label="City" required error={errors.city} htmlFor="rq-city"
              action={
                <button type="button" className="u-link text-[0.75rem]"
                  onClick={() => { setCityMode(cityMode === "select" ? "pincode" : "select"); set("city", ""); }}>
                  {cityMode === "select" ? "Use a pincode" : "Pick a city"}
                </button>
              }>
              {cityMode === "select" ? (
                <NamedSelect id="rq-city" value={d.city} onChange={setCity} items={cities} placeholder="Pick one" />
              ) : (
                <input id="rq-city" className="u-input" placeholder="e.g. 700001" value={d.city} onChange={(e) => set("city", e.target.value)} />
              )}
            </Field>
          )}

          {/* ---- The load-bearing bit ---- */}
          <div className="u-field">
            <div className="flex items-baseline justify-between">
              <span className="u-label">When are you free? <span className="text-danger">*</span></span>
              <span className="text-[0.6875rem] text-ink-400">{TZ}</span>
            </div>
            <p className="u-hint">Add every slot you could do — the more you add, the more teachers can reach you.</p>

            <div className="mt-2 flex flex-col gap-2">
              {d.windows.map((w, i) => (
                <div key={i} className="rounded-xl border border-ink-300 bg-paper p-3">
                  <div className="flex items-center gap-2">
                    <select className="u-select min-h-[40px] flex-1 py-1.5" value={w.day_of_week}
                      onChange={(e) => setWindow(i, { day_of_week: Number(e.target.value) })} aria-label={`Day for slot ${i + 1}`}>
                      {DAYS.map((day) => <option key={day.n} value={day.n}>{day.full}</option>)}
                    </select>
                    {d.windows.length > 1 && (
                      <button type="button" className="u-btn-ghost u-btn-sm text-danger"
                        onClick={() => setD((p) => ({ ...p, windows: p.windows.filter((_, j) => j !== i) }))}
                        aria-label={`Remove slot ${i + 1}`}>✕</button>
                    )}
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <input type="time" step={900} className="u-input min-h-[40px] flex-1 py-1.5" value={w.start_time}
                      onChange={(e) => setWindow(i, { start_time: e.target.value })} aria-label={`Start time for slot ${i + 1}`} />
                    <span className="text-[0.75rem] text-ink-500">to</span>
                    <input type="time" step={900} className="u-input min-h-[40px] flex-1 py-1.5" value={w.end_time}
                      onChange={(e) => setWindow(i, { end_time: e.target.value })} aria-label={`End time for slot ${i + 1}`} />
                  </div>
                </div>
              ))}
            </div>
            <button type="button" className="u-btn-ghost u-btn-sm mt-2 text-pine-700"
              onClick={() => setD((p) => ({ ...p, windows: [...p.windows, blankWindow()] }))}>
              + Add another time
            </button>
            {errors.schedule && <p className="u-error mt-1">{errors.schedule}</p>}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Budget from (₹/month)" error={errors.budget_min} htmlFor="rq-bmin">
              <input id="rq-bmin" type="number" min={0} className="u-input" value={d.budget_min}
                onChange={(e) => set("budget_min", e.target.value)} placeholder="Any" />
            </Field>
            <Field label="up to (₹/month)" htmlFor="rq-bmax">
              <input id="rq-bmax" type="number" min={0} className="u-input" value={d.budget_max}
                onChange={(e) => set("budget_max", e.target.value)} placeholder="Any" />
            </Field>
          </div>

          <Field label="How long is a class?" htmlFor="rq-dur">
            <select id="rq-dur" className="u-select" value={d.class_duration_minutes}
              onChange={(e) => set("class_duration_minutes", Number(e.target.value))}>
              {[30, 45, 60, 90, 120].map((m) => <option key={m} value={m}>{m} minutes</option>)}
            </select>
          </Field>

          <Field label="Anything else?" htmlFor="rq-desc">
            <textarea id="rq-desc" className="u-textarea" placeholder="Goals, exam you're preparing for, where you're stuck…"
              spellCheck={false} autoCorrect="off" autoCapitalize="off"
              value={d.description} onChange={(e) => set("description", e.target.value)} />
          </Field>

          <div className="sticky bottom-0 -mx-5 -mb-5 flex gap-2 border-t border-ink-200 bg-paper px-5 py-4">
            <button type="button" className="u-btn-secondary flex-1" onClick={onClose}>Cancel</button>
            <button type="submit" className="u-btn-primary flex-1" data-loading={saving || undefined} disabled={saving}>
              {editing ? "Save changes" : "Post it"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/**
 * "Which languages, in order of preference?" - an "Any language" toggle
 * (same shape/copy convention as WindowPicker's "I'm flexible") plus a
 * ranked, reorderable list. Adding from the taxonomy list is a
 * TaxonomyCombobox (shared with Discover/Search's search-box pickers);
 * "Type it in" is the same per-item free-text escape the subject field
 * has, for a language genuinely missing from the taxonomy - the backend
 * auto-creates it exactly like an unrecognized subject does.
 */
function LanguageRankPicker({
  languages, allLanguages, noPreference, onChange, onToggleNoPreference, addMode, onToggleAddMode,
}: {
  languages: string[];
  allLanguages: Named[];
  noPreference: boolean;
  onChange: (languages: string[]) => void;
  onToggleNoPreference: () => void;
  addMode: "select" | "custom";
  onToggleAddMode: () => void;
}) {
  const [customText, setCustomText] = useState("");
  const atMax = languages.length >= MAX_PREFERRED_LANGUAGES;
  const available = allLanguages
    .map((l) => l.name)
    .filter((name) => !languages.includes(name));

  function add(name: string | null) {
    const trimmed = name?.trim();
    if (!trimmed || atMax || languages.includes(trimmed)) return;
    onChange([...languages, trimmed]);
  }
  function remove(i: number) {
    onChange(languages.filter((_, j) => j !== i));
  }
  function move(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= languages.length) return;
    const next = [...languages];
    [next[i], next[j]] = [next[j]!, next[i]!];
    onChange(next);
  }

  return (
    <div>
      <button type="button" aria-pressed={noPreference} onClick={onToggleNoPreference}
        className={
          "flex w-full items-start gap-2.5 rounded-xl border-[1.5px] px-3.5 py-2.5 text-left transition duration-150 ease-enter " +
          (noPreference ? "border-pine-600 bg-pine-50" : "border-ink-300 bg-paper hover:border-pine-400 hover:bg-pine-50")
        }>
        <span
          className={
            "mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full border-[1.5px] " +
            (noPreference ? "border-pine-600 bg-pine-600" : "border-ink-300")
          }>
          {noPreference && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
        </span>
        <span>
          <span className="block text-[0.875rem] font-semibold text-ink-900">Any language</span>
          <span className="block text-[0.75rem] text-ink-500">No preference - show every match regardless of language.</span>
        </span>
      </button>

      {!noPreference && (
        <div className="mt-3 flex flex-col gap-2">
          {languages.length > 0 && (
            <ol className="flex flex-col gap-1.5">
              {languages.map((name, i) => (
                <li key={name} className="flex items-center gap-1.5 rounded-xl border border-ink-300 bg-paper px-2.5 py-1.5">
                  <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-pine-100 text-[0.6875rem] font-bold text-pine-700">
                    {i + 1}
                  </span>
                  <span className="flex-1 truncate text-[0.875rem] text-ink-900">{name}</span>
                  <button type="button" className="u-btn-ghost u-btn-sm shrink-0" disabled={i === 0}
                    onClick={() => move(i, -1)} aria-label={`Move ${name} up`}>↑</button>
                  <button type="button" className="u-btn-ghost u-btn-sm shrink-0" disabled={i === languages.length - 1}
                    onClick={() => move(i, 1)} aria-label={`Move ${name} down`}>↓</button>
                  <button type="button" className="u-btn-ghost u-btn-sm shrink-0 text-danger"
                    onClick={() => remove(i)} aria-label={`Remove ${name}`}>✕</button>
                </li>
              ))}
            </ol>
          )}

          {atMax ? (
            <p className="u-fine">You've picked the max of {MAX_PREFERRED_LANGUAGES} languages.</p>
          ) : (
            <div className="flex items-start justify-between gap-2">
              {addMode === "select" ? (
                <div className="flex-1">
                  <TaxonomyCombobox key={languages.length} id="rq-lang-add" items={available} value={null}
                    onChange={add} placeholder={languages.length ? "Add another language" : "Search languages — e.g. Hindi"}
                    emptyHint="No languages have been added yet." />
                </div>
              ) : (
                <div className="flex flex-1 gap-1.5">
                  <input className="u-input" maxLength={60} placeholder="e.g. Tulu, Sindhi, Sign Language"
                    value={customText} onChange={(e) => setCustomText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") { e.preventDefault(); add(customText); setCustomText(""); }
                    }} />
                  <button type="button" className="u-btn-secondary u-btn-sm shrink-0"
                    onClick={() => { add(customText); setCustomText(""); }}>Add</button>
                </div>
              )}
              <button type="button" className="u-link mt-2 shrink-0 text-[0.75rem]" onClick={onToggleAddMode}>
                {addMode === "select" ? "Type it in" : "Pick from list"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * A <select> backed by a taxonomy list - subjects/cities can run into the
 * hundreds of options. Every keystroke in ANY field (the description
 * textarea included) used to re-render this whole form, which meant
 * re-creating all those <option> elements on every character typed.
 * React.memo skips that unless this select's own props actually changed -
 * `items` stays referentially stable from React Query, and the callers
 * pass stable (useCallback'd) `onChange` handlers, so typing elsewhere no
 * longer touches this.
 */
const NamedSelect = memo(function NamedSelect({
  id, value, onChange, items, placeholder,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  items: Named[];
  placeholder: string;
}) {
  return (
    <select id={id} className="u-select" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {items.map((it) => <option key={it.id} value={it.name}>{it.name}</option>)}
    </select>
  );
});

function Field({
  label, children, required, error, htmlFor, action,
}: {
  label: string;
  children: React.ReactNode;
  required?: boolean;
  error?: string;
  htmlFor?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="u-field">
      <div className="flex items-baseline justify-between gap-2">
        <label className="u-label" htmlFor={htmlFor}>
          {label} {required && <span className="text-danger">*</span>}
        </label>
        {action}
      </div>
      {children}
      {error && <p className="u-error">{error}</p>}
    </div>
  );
}
