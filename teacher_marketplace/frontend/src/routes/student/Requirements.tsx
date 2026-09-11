import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { Named, StudentRequirement } from "@/lib/types";
import { DAYS } from "@/lib/intent";
import { confirmAction, money, titleCase, toast } from "@/lib/ui";

/**
 * What you're looking for.
 *
 * This is the actual conversion action in this marketplace: students don't
 * message teachers, they post a requirement and matched teachers reach out.
 * So the empty state is a pitch, not an apology, and the form is the one
 * place worth spending screen on.
 *
 * The schedule rows are the load-bearing part — the matching engine scores
 * real time overlap, so every extra window a student adds widens who can
 * reach them. The copy says that rather than leaving it implied.
 */

const TZ = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
  } catch {
    return "Asia/Kolkata";
  }
})();

interface Window_ {
  day_of_week: number;
  start_time: string;
  end_time: string;
  flexibility: "flexible" | "fixed";
}

interface Draft {
  subject: string;
  student_class: string;
  preferred_language: string;
  teaching_mode: "online" | "offline" | "both";
  city: string;
  budget_min: string;
  budget_max: string;
  class_duration_minutes: number;
  preferred_timing: string;
  description: string;
  windows: Window_[];
}

const blankWindow = (): Window_ => ({ day_of_week: 1, start_time: "18:00", end_time: "19:00", flexibility: "flexible" });

const blankDraft = (): Draft => ({
  subject: "", student_class: "", preferred_language: "", teaching_mode: "online", city: "",
  budget_min: "", budget_max: "", class_duration_minutes: 60,
  preferred_timing: "", description: "", windows: [blankWindow()],
});

export function Requirements() {
  const qc = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["requirements"],
    queryFn: () => api.list<StudentRequirement>("/student-requirements/"),
  });

  const items = data?.items ?? [];

  async function withdraw(r: StudentRequirement) {
    const ok = await confirmAction({
      title: "Take this down?",
      message: "Teachers won't be matched to it any more. You can't undo this.",
      confirmLabel: "Take it down",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.del(`/student-requirements/${r.id}/`);
      toast("success", "Taken down.");
      qc.invalidateQueries({ queryKey: ["requirements"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't take it down.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="u-h2">
          {isLoading ? "Loading…" : items.length ? `${items.length} request${items.length === 1 ? "" : "s"} out there` : "What you're looking for"}
        </h1>
        {items.length > 0 && (
          <button type="button" className="u-btn-primary" onClick={() => setFormOpen(true)}>
            Post another
          </button>
        )}
      </div>

      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i} className="h-44 animate-pulse rounded-2xl bg-ink-100" />
          ))}
        </div>
      )}

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? "Couldn't load these."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <section className="u-card flex flex-col items-center gap-4 px-6 py-14 text-center">
          <span className="grid h-14 w-14 place-items-center rounded-2xl bg-pine-700 text-white">
            <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
              <rect x="8" y="4" width="8" height="4" rx="1" />
              <path d="M9 4H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3M9 12h6M9 16h4" />
            </svg>
          </span>
          <div className="max-w-prose">
            <h2 className="u-h3">Tell us once. Teachers come to you.</h2>
            <p className="u-body mt-2 text-ink-600">
              Say what you want to learn, in which language, and when you're free. Matching teachers get in touch —
              you never pay a rupee.
            </p>
          </div>
          <button type="button" className="u-btn-primary u-btn-lg" onClick={() => setFormOpen(true)}>
            Post what you need
          </button>
        </section>
      )}

      {items.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          {items.map((r) => (
            <RequirementCard key={r.id} r={r} onWithdraw={() => withdraw(r)} />
          ))}
        </div>
      )}

      {formOpen && (
        <RequirementForm
          onClose={() => setFormOpen(false)}
          onSaved={() => {
            setFormOpen(false);
            qc.invalidateQueries({ queryKey: ["requirements"] });
          }}
        />
      )}
    </div>
  );
}

function RequirementCard({ r, onWithdraw }: { r: StudentRequirement; onWithdraw: () => void }) {
  const open = r.status === "open";
  const budget =
    r.budget_min || r.budget_max ? `${money(r.budget_min) ?? "—"} – ${money(r.budget_max) ?? "—"}` : "Any";

  return (
    <article className="u-card u-card-pad flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-[1rem] font-semibold text-ink-900">{r.subject?.name ?? "Subject"}</h2>
          <p className="u-fine mt-0.5">
            {[titleCase(r.teaching_mode), r.student_class].filter(Boolean).join(" · ")}
          </p>
        </div>
        <span className={open ? "u-badge u-badge-pine" : "u-badge u-badge-ink"}>{titleCase(r.status)}</span>
      </div>

      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-[0.8125rem]">
        <Cell label="Budget" value={budget} />
        <Cell label="Language" value={r.preferred_language?.name ?? "Any"} />
        <Cell label="Where" value={r.city?.name ?? (r.teaching_mode === "online" ? "Online" : "—")} />
        <Cell label="Posted" value={new Date(r.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} />
      </dl>

      <div className="mt-auto flex gap-2 border-t border-ink-200 pt-3">
        <a href={`/student/requirements/${r.id}/`} className="u-btn-secondary u-btn-sm flex-1">Open</a>
        <button type="button" className="u-btn-ghost u-btn-sm text-danger hover:bg-danger/5" onClick={onWithdraw}>
          Take down
        </button>
      </div>
    </article>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">{label}</dt>
      <dd className="mt-0.5 font-medium text-ink-900">{value}</dd>
    </div>
  );
}

/* ------------------------------------------------------------------ */

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

function RequirementForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const { subjects, languages, grades, cities } = useOptions();
  const [d, setD] = useState<Draft>(blankDraft);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [nonField, setNonField] = useState("");
  const [saving, setSaving] = useState(false);
  const [cityMode, setCityMode] = useState<"select" | "pincode">("select");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => {
    setD((p) => ({ ...p, [k]: v }));
    setErrors((e) => {
      const { [k as string]: _drop, ...rest } = e;
      return rest;
    });
  };

  const setWindow = (i: number, patch: Partial<Window_>) =>
    setD((p) => ({ ...p, windows: p.windows.map((w, j) => (j === i ? { ...w, ...patch } : w)) }));

  function validate(): boolean {
    const next: Record<string, string> = {};
    if (!d.subject) next.subject = "Pick a subject.";
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
      for (const k of ["student_class", "preferred_language", "city", "preferred_timing", "description"] as const) {
        if (d[k]) payload[k] = d[k];
      }
      for (const k of ["budget_min", "budget_max"] as const) {
        if (d[k]) payload[k] = Number(d[k]);
      }

      await api.post("/student-requirements/", payload, { silent: true });
      toast("success", "Posted. We're matching you with teachers now.");
      onSaved();
    } catch (err) {
      const e2 = err as ApiError;
      if (e2.fieldErrors) setErrors(e2.fieldErrors);
      else setNonField(e2.message || "Couldn't post that.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Post what you need">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l border-ink-300 bg-paper shadow-raise">
        <header className="flex items-center justify-between gap-3 border-b border-ink-200 px-5 py-4">
          <h2 className="u-h3">What do you need?</h2>
          <button type="button" className="u-btn-ghost u-btn-sm" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <form className="flex flex-1 flex-col gap-4 overflow-y-auto p-5" onSubmit={save}>
          {nonField && <div className="u-alert u-alert-error">{nonField}</div>}

          <Field label="Subject" required error={errors.subject} htmlFor="rq-subject">
            <select id="rq-subject" className="u-select" value={d.subject} onChange={(e) => set("subject", e.target.value)}>
              <option value="">Pick one</option>
              {subjects.map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
            </select>
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Level" htmlFor="rq-class">
              <select id="rq-class" className="u-select" value={d.student_class} onChange={(e) => set("student_class", e.target.value)}>
                <option value="">Any</option>
                {grades.map((g) => <option key={g.id} value={g.name}>{g.name}</option>)}
              </select>
            </Field>
            <Field label="Language" htmlFor="rq-lang">
              <select id="rq-lang" className="u-select" value={d.preferred_language} onChange={(e) => set("preferred_language", e.target.value)}>
                <option value="">Any</option>
                {languages.map((l) => <option key={l.id} value={l.name}>{l.name}</option>)}
              </select>
            </Field>
          </div>

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
                <select id="rq-city" className="u-select" value={d.city} onChange={(e) => set("city", e.target.value)}>
                  <option value="">Pick one</option>
                  {cities.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
                </select>
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
            <Field label="Budget from (₹)" error={errors.budget_min} htmlFor="rq-bmin">
              <input id="rq-bmin" type="number" min={0} className="u-input" value={d.budget_min}
                onChange={(e) => set("budget_min", e.target.value)} placeholder="Any" />
            </Field>
            <Field label="up to (₹)" htmlFor="rq-bmax">
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
              value={d.description} onChange={(e) => set("description", e.target.value)} />
          </Field>

          <div className="sticky bottom-0 -mx-5 -mb-5 flex gap-2 border-t border-ink-200 bg-paper px-5 py-4">
            <button type="button" className="u-btn-secondary flex-1" onClick={onClose}>Cancel</button>
            <button type="submit" className="u-btn-primary flex-1" data-loading={saving || undefined} disabled={saving}>
              Post it
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

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
