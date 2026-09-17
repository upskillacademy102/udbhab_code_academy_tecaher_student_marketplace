import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { StudentRequirement } from "@/lib/types";
import { DAYS } from "@/lib/intent";
import { confirmAction, languageLabel, moneyRange, titleCase, toast } from "@/lib/ui";
import { RequirementForm, draftFromRequirement } from "@/components/RequirementForm";

/**
 * One request, and what has happened to it since.
 *
 * The status line is the point. A student who posts a requirement and then
 * sees a static row has no idea whether anything is happening; showing the
 * distribution state as plain English is the difference between "posted into
 * a void" and "it's working".
 */

function distributionLine(status: string | null | undefined): { text: string; tone: "working" | "done" | "problem" } {
  switch (status) {
    case "completed":
      return { text: "Sent to matching teachers. They'll get in touch with you directly.", tone: "done" };
    case "failed":
      return { text: "Matching didn't finish. Open the request, change anything, and save to try again.", tone: "problem" };
    case "pending":
    case "in_progress":
      return { text: "We're matching you with teachers right now.", tone: "working" };
    default:
      return { text: "We're matching you with teachers.", tone: "working" };
  }
}

export function RequirementDetail() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);

  const { data: r, isLoading, isError, error } = useQuery<StudentRequirement>({
    queryKey: ["requirement", id],
    queryFn: () => api.get<StudentRequirement>(`/student-requirements/${id}/`),
  });

  async function close() {
    const ok = await confirmAction({
      title: "Close this request?",
      message: "No more teachers will be matched to it.",
      confirmLabel: "Close it",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.patch(`/student-requirements/${id}/`, { status: "closed" });
      toast("success", "Closed.");
      qc.invalidateQueries({ queryKey: ["requirement", id] });
      qc.invalidateQueries({ queryKey: ["requirements"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't close it.");
    }
  }

  if (isLoading) return <div className="h-96 animate-pulse rounded-2xl bg-ink-100" />;

  if (isError || !r) {
    const notFound = (error as { status?: number })?.status === 404;
    return (
      <section className="u-card flex flex-col items-center gap-4 px-6 py-14 text-center">
        <h1 className="u-h3">{notFound ? "We can't find that request" : "Couldn't load that request"}</h1>
        <Link to="/student/requirements/" className="u-btn-primary">Back to your requests</Link>
      </section>
    );
  }

  const open = r.status === "open";
  // Editable regardless of status - "matched" flips the moment a teacher
  // is merely soft-matched, long before anyone actually unlocks the
  // student's contact details. That unlock is the real lock.
  const editable = !r.has_unlocked_lead;
  const dist = distributionLine(r.lead_distribution_status);
  const windows = r.schedule_preferences ?? [];

  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <Link to="/student/requirements/" className="u-link -mt-1 text-[0.875rem]">← All your requests</Link>

      <section className="u-card u-card-pad">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="u-h2">{r.subject?.name ?? "Subject"}</h1>
            <p className="u-fine mt-1">
              {[titleCase(r.teaching_mode), r.student_class, languageLabel(r.no_language_preference, r.preferred_languages)]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
          <span className={open ? "u-badge u-badge-pine" : "u-badge u-badge-ink"}>{titleCase(r.status)}</span>
        </div>

        {open && (
          <div
            className={
              "mt-4 rounded-xl border px-4 py-3 text-[0.875rem] " +
              (dist.tone === "problem"
                ? "border-danger/30 bg-danger/5 text-danger"
                : dist.tone === "done"
                  ? "border-pine-300 bg-pine-50 text-pine-900"
                  : "border-marigold-300 bg-marigold-50 text-marigold-900")
            }
          >
            {dist.text}
          </div>
        )}
      </section>

      <section className="u-card u-card-pad">
        <h2 className="u-eyebrow">The details</h2>
        <dl className="mt-3 grid gap-x-6 gap-y-4 sm:grid-cols-2">
          <Row label="Budget" value={moneyRange(r.budget_min, r.budget_max) ? `${moneyRange(r.budget_min, r.budget_max)} / mo` : "Any"} />
          <Row label="Language" value={languageLabel(r.no_language_preference, r.preferred_languages)} />
          <Row label="Where" value={r.city?.name ?? (r.teaching_mode === "online" ? "Online" : "—")} />
          <Row label="Class length" value={r.class_duration_minutes ? `${r.class_duration_minutes} minutes` : "—"} />
          <Row label="Posted" value={new Date(r.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })} />
          {r.preferred_timing && <Row label="Timing notes" value={r.preferred_timing} />}
        </dl>

        {r.description && (
          <div className="mt-5 border-t border-ink-200 pt-4">
            <h3 className="u-eyebrow">What you said</h3>
            <p className="u-body mt-2 whitespace-pre-line text-ink-700">{r.description}</p>
          </div>
        )}
      </section>

      <section className="u-card u-card-pad">
        <h2 className="u-eyebrow">When you're free</h2>
        {windows.length === 0 ? (
          <p className="u-body mt-2 text-ink-600">No times given, so we can't rank teachers by who actually fits.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2">
            {windows.map((w) => (
              <li key={w.id} className="flex items-center justify-between gap-3 rounded-xl border border-ink-200 px-4 py-2.5">
                <span className="text-[0.9375rem] font-medium text-ink-900">
                  {w.day_of_week_label ?? DAYS.find((d) => d.n === w.day_of_week)?.full ?? "—"}
                </span>
                <span className="text-[0.875rem] tabular-nums text-ink-600">
                  {w.start_time.slice(0, 5)} – {w.end_time.slice(0, 5)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {(editable || open) && (
        <div className="flex justify-end gap-2">
          {editable && (
            <button type="button" className="u-btn-secondary" onClick={() => setEditing(true)}>
              Edit
            </button>
          )}
          {open && (
            <button type="button" className="u-btn-secondary" onClick={close}>
              Close this request
            </button>
          )}
        </div>
      )}

      {editing && (
        <RequirementForm
          requirementId={r.id}
          initial={draftFromRequirement(r)}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            qc.invalidateQueries({ queryKey: ["requirement", id] });
            qc.invalidateQueries({ queryKey: ["requirements"] });
          }}
        />
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">{label}</dt>
      <dd className="mt-0.5 text-[0.9375rem] font-medium text-ink-900">{value}</dd>
    </div>
  );
}
