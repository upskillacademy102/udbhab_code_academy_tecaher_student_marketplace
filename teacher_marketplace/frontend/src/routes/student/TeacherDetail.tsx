import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TeacherProfile, TeacherRef } from "@/lib/types";
import { DAYS } from "@/lib/intent";
import { confirmAction, initials, money, moneyRange, toast } from "@/lib/ui";

/**
 * One teacher, in full.
 *
 * This page's real job is turning interest into a requirement — there is no
 * student-to-teacher messaging in this product, so "contact" is not an
 * action that exists. The primary CTA posts a requirement, which is what
 * actually reaches the teacher.
 *
 * Everything the Django version did is preserved: the schedule-fit checker,
 * reporting, blocking, and the instant hydrate from the search result the
 * student clicked (sessionStorage), so the page paints before the API
 * answers.
 */

const REPORT_REASONS = [
  { id: "off_platform", label: "Asked to pay or chat off-platform" },
  { id: "spam", label: "Spam or scam" },
  { id: "abuse", label: "Abusive behaviour" },
  { id: "impersonation", label: "Fake profile" },
  { id: "no_show", label: "Didn't show up" },
  { id: "other", label: "Something else" },
] as const;

interface SlotCheck {
  ok: boolean;
  message: string;
}

/**
 * Everything the marketplace knows is optional here, deliberately.
 *
 * There is no endpoint that returns another teacher's marketplace profile by
 * id — teacher_profile's own route is teacher-only, and /teachers/{id}/
 * returns the person (bio, experience, qualification) without subjects,
 * languages, rate or rating. Those only ever arrive via a search result,
 * which is why the search grid stashes each card in sessionStorage before
 * navigating.
 *
 * So a click from search renders in full, and a cold direct link renders the
 * person with the marketplace details absent rather than blank or invented.
 */
type DetailData = Partial<TeacherProfile> & { teacher?: TeacherRef };

function cachedTeacher(id: string): TeacherProfile | null {
  try {
    const raw = sessionStorage.getItem("tp:" + id);
    return raw ? (JSON.parse(raw) as TeacherProfile) : null;
  } catch {
    return null;
  }
}

export function TeacherDetail() {
  const { id = "" } = useParams();
  const seed = cachedTeacher(id);

  const { data, isLoading, isError, error } = useQuery<DetailData>({
    queryKey: ["teacher", id],
    queryFn: async () => {
      const base = await api.get<TeacherRef>(`/teachers/${id}/`, { silent: true });
      // The seed carries the marketplace half; `base` is the authoritative
      // person record, so it wins for bio/experience/qualification.
      return { ...(seed ?? {}), teacher: base };
    },
    initialData: seed ?? undefined,
  });

  const t = data;
  // Only claim "not found" when there is genuinely nothing to show. If the
  // card handed data forward, render it even if the person fetch failed —
  // a blank error page over perfectly good data is the worse outcome.
  const notFound = !t && isError && (error as { status?: number })?.status === 404;

  if (notFound) {
    return (
      <section className="u-card flex flex-col items-center gap-4 px-6 py-14 text-center">
        <h1 className="u-h3">We can't find that teacher</h1>
        <p className="u-body max-w-prose text-ink-600">They may have taken their profile down.</p>
        <Link to="/student/teachers/" className="u-btn-primary">Back to search</Link>
      </section>
    );
  }

  if (isLoading && !t) {
    return (
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="flex flex-col gap-4 lg:col-span-2">
          <div className="h-40 animate-pulse rounded-2xl bg-ink-100" />
          <div className="h-48 animate-pulse rounded-2xl bg-ink-100" />
        </div>
        <div className="h-64 animate-pulse rounded-2xl bg-ink-100" />
      </div>
    );
  }

  if (!t) {
    return (
      <div className="u-alert u-alert-error">
        <span>{(error as { message?: string })?.message ?? "Couldn't load this teacher."}</span>
      </div>
    );
  }

  const name = t.teacher?.user?.full_name ?? "Teacher";
  const photo = t.teacher?.profile_photo;
  const rating = Number(t.rating ?? 0);
  const years = t.years_of_experience ?? t.teacher?.experience_years ?? null;
  const city = t.cities?.[0]?.name ?? "";
  const qual = [t.teacher?.qualification_level, t.teacher?.qualification_detail].filter(Boolean).join(" — ");
  const hourlyPrice = money(t.hourly_rate);
  const monthlyPrice = moneyRange(t.monthly_rate, t.monthly_rate_max);
  const price = hourlyPrice ?? monthlyPrice;
  const priceUnit = hourlyPrice ? "per hour" : "per month";
  const subjects = t.subjects ?? [];
  const languages = t.languages ?? [];

  return (
    <div className="flex flex-col gap-6">
      <Link to="/student/teachers/" className="u-link -mt-1 text-[0.875rem]">← Back to search</Link>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="flex flex-col gap-5 lg:col-span-2">
          {/* ---- Who ---- */}
          <section className="u-card u-card-pad">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
              {photo ? (
                <img src={photo} alt="" className="h-24 w-24 shrink-0 rounded-2xl object-cover object-top" />
              ) : (
                <span className="grid h-24 w-24 shrink-0 place-items-center rounded-2xl bg-pine-100 text-2xl font-bold text-pine-800">
                  {initials(name)}
                </span>
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h1 className="u-h3">{name}</h1>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      {t.is_fully_verified ? (
                        <span className="u-badge u-badge-pine">ID &amp; qualifications checked</span>
                      ) : t.is_verified ? (
                        <span className="u-badge u-badge-pine">Verified</span>
                      ) : null}
                      {rating > 0 ? (
                        <span className="text-[0.875rem] font-semibold tabular-nums text-ink-900">★ {rating.toFixed(1)}</span>
                      ) : (
                        <span className="u-badge u-badge-ink">New teacher</span>
                      )}
                    </div>
                  </div>
                  {price && (
                    <div className="shrink-0 text-right">
                      <p className="font-display text-2xl font-bold tabular-nums text-ink-900">{price}</p>
                      <p className="u-fine">{priceUnit}</p>
                      {hourlyPrice && monthlyPrice && (
                        <p className="u-fine mt-0.5">{monthlyPrice} / month</p>
                      )}
                    </div>
                  )}
                </div>

                {t.headline && <p className="u-body mt-3 text-ink-700">{t.headline}</p>}

                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[0.8125rem] text-ink-600">
                  {t.teaching_mode && <span className="capitalize">{t.teaching_mode === "both" ? "Online or in person" : t.teaching_mode}</span>}
                  {years != null && <span>{years} yr{years === 1 ? "" : "s"} experience</span>}
                  {city && <span>{city}</span>}
                </div>
              </div>
            </div>
          </section>

          {t.teacher?.bio && (
            <section className="u-card u-card-pad">
              <h2 className="u-eyebrow">About</h2>
              <p className="u-body mt-2.5 whitespace-pre-line text-ink-700">{t.teacher.bio}</p>
            </section>
          )}

          <section className="u-card u-card-pad flex flex-col gap-4">
            {subjects.length > 0 && (
              <div>
                <h2 className="u-eyebrow">Teaches</h2>
                <div className="mt-2 flex flex-wrap gap-2">
                  {subjects.map((s) => (
                    <span key={s.id} className="u-chip u-chip-sm pointer-events-none">{s.name}</span>
                  ))}
                </div>
              </div>
            )}
            {languages.length > 0 && (
              <div>
                <h2 className="u-eyebrow">In these languages</h2>
                <div className="mt-2 flex flex-wrap gap-2">
                  {languages.map((l) => (
                    <span key={l.id} className="u-chip u-chip-sm pointer-events-none">{l.name}</span>
                  ))}
                </div>
              </div>
            )}
            {qual && (
              <div>
                <h2 className="u-eyebrow">Qualification</h2>
                <p className="u-body mt-1.5 capitalize text-ink-700">{qual.replace(/_/g, " ")}</p>
              </div>
            )}
          </section>
        </div>

        {/* ---- Sidebar ---- */}
        <div className="flex flex-col gap-5 lg:sticky lg:top-20 lg:self-start">
          <ScheduleCheck teacherId={id} />

          <section className="u-card u-card-pad border-pine-300 bg-pine-50">
            <h2 className="u-h3">Want to learn with {name.split(" ")[0]}?</h2>
            <p className="u-body mt-1.5 text-ink-700">
              Post what you need and we'll take it to them — and to anyone else who fits. They get in touch with you.
            </p>
            <Link to="/student/requirements/" className="u-btn-primary mt-4 w-full">Post what you need</Link>
            <p className="u-fine mt-2 text-center">Always free for students.</p>
          </section>

          <SafetyBox teacher={t} />
        </div>
      </div>
    </div>
  );
}

/** Does this teacher's week overlap a time the student can do? */
function ScheduleCheck({ teacherId }: { teacherId: string }) {
  const [day, setDay] = useState(1);
  const [start, setStart] = useState("18:00");
  const [end, setEnd] = useState("19:00");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SlotCheck | null>(null);

  async function check(e: React.FormEvent) {
    e.preventDefault();
    if (!start || !end) return toast("warning", "Pick a start and end time.");
    if (start >= end) return toast("warning", "The end time has to be after the start time.");
    setBusy(true);
    setResult(null);
    try {
      const r = await api.get<Record<string, unknown>>(`/teachers/${teacherId}/best-slots/`, {
        params: {
          day,
          start_time: start,
          end_time: end,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata",
        },
        silent: true,
      });
      const best = (r?.best_matching_time ?? r?.best_slot) as string | undefined;
      const score = Number(r?.time_score ?? r?.match_percentage ?? 0);
      if (best || score > 0) {
        setResult({ ok: true, message: best ? `Yes — they're free ${best}.` : `That works. ${Math.round(score)}% overlap.` });
      } else {
        setResult({ ok: false, message: "They're not free then. Try another time." });
      }
    } catch (err) {
      setResult({
        ok: false,
        message:
          (err as { status?: number })?.status === 400
            ? "That time range doesn't look right."
            : "Couldn't check just now.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="u-card u-card-pad">
      <h2 className="u-h3">Can they do your time?</h2>
      <p className="u-fine mt-1">Pick a slot you're free and we'll check.</p>
      <form className="mt-4 flex flex-col gap-3" onSubmit={check}>
        <div className="u-field">
          <label className="u-label" htmlFor="sc-day">Day</label>
          <select id="sc-day" className="u-select" value={day} onChange={(e) => setDay(Number(e.target.value))}>
            {DAYS.map((d) => (
              <option key={d.n} value={d.n}>{d.full}</option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="u-field">
            <label className="u-label" htmlFor="sc-from">From</label>
            <input id="sc-from" type="time" className="u-input" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="u-field">
            <label className="u-label" htmlFor="sc-to">To</label>
            <input id="sc-to" type="time" className="u-input" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
        </div>
        <button type="submit" className="u-btn-secondary w-full" data-loading={busy || undefined} disabled={busy}>
          Check
        </button>
      </form>
      {result && (
        <div
          className={
            "mt-3 rounded-xl border px-3.5 py-3 text-[0.875rem] " +
            (result.ok ? "border-pine-300 bg-pine-50 text-pine-900" : "border-ink-300 bg-paper-sunk text-ink-700")
          }
        >
          {result.message}
        </div>
      )}
    </section>
  );
}

function SafetyBox({ teacher }: { teacher: DetailData }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<string>(REPORT_REASONS[0].id);
  const [detail, setDetail] = useState("");
  const [sending, setSending] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [blocking, setBlocking] = useState(false);

  const userId = teacher.teacher?.user?.id ?? null;

  async function report() {
    if (!userId) return toast("error", "We couldn't identify this teacher.");
    setSending(true);
    try {
      await api.post("/safety/report/", { user_id: userId, reason, detail });
      toast("success", "Report sent. Thank you.");
      setOpen(false);
      setDetail("");
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't send that report.");
    } finally {
      setSending(false);
    }
  }

  async function block() {
    if (!userId || blocked) return;
    const ok = await confirmAction({
      title: "Hide this teacher?",
      message: "They won't show up in your results again.",
      confirmLabel: "Hide them",
      danger: true,
    });
    if (!ok) return;
    setBlocking(true);
    try {
      await api.post("/safety/blocks/", { user_id: userId });
      setBlocked(true);
      toast("success", "Hidden. They won't appear in your results.");
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't do that.");
    } finally {
      setBlocking(false);
    }
  }

  return (
    <section className="u-card u-card-pad">
      <h2 className="u-h3">Something not right?</h2>
      <p className="u-fine mt-1">Tell us, or hide them from your results.</p>
      <div className="mt-3 flex gap-2">
        <button type="button" className="u-btn-secondary u-btn-sm flex-1" onClick={() => setOpen((v) => !v)}>
          Report
        </button>
        <button
          type="button"
          className="u-btn-secondary u-btn-sm flex-1"
          onClick={block}
          data-loading={blocking || undefined}
          disabled={blocked || blocking}
        >
          {blocked ? "Hidden" : "Hide"}
        </button>
      </div>

      {open && (
        <div className="mt-3 flex flex-col gap-2.5">
          <div className="u-field">
            <label className="u-label" htmlFor="rp-reason">What happened?</label>
            <select id="rp-reason" className="u-select" value={reason} onChange={(e) => setReason(e.target.value)}>
              {REPORT_REASONS.map((r) => (
                <option key={r.id} value={r.id}>{r.label}</option>
              ))}
            </select>
          </div>
          <textarea
            className="u-textarea"
            rows={2}
            maxLength={1000}
            placeholder="Anything else we should know? (optional)"
            value={detail}
            onChange={(e) => setDetail(e.target.value)}
          />
          <div className="flex gap-2">
            <button type="button" className="u-btn-primary u-btn-sm flex-1" onClick={report} data-loading={sending || undefined}>
              Send
            </button>
            <button type="button" className="u-btn-ghost u-btn-sm" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
