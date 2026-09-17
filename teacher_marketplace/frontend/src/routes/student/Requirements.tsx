import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { StudentRequirement } from "@/lib/types";
import { clearIntent, readIntent } from "@/lib/intent";
import { confirmAction, languageLabel, moneyRange, titleCase, toast } from "@/lib/ui";
import { RequirementForm, draftFromRequirement, type Draft } from "@/components/RequirementForm";

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

/**
 * What a "no teachers matched" search on Discover already answered, carried
 * over so posting a requirement doesn't ask the student to retype the same
 * subject/language/schedule a screen later. Read once and cleared, same
 * handoff Discover itself uses for the pre-login sign-up answers.
 */
function useIncomingIntent(): Partial<Draft> | null {
  return useMemo(() => {
    const intent = readIntent();
    if (!intent) return null;
    clearIntent();
    if (!intent.subject && !intent.language) return null;
    const draft: Partial<Draft> = {};
    if (intent.subject) draft.subject = intent.subject;
    if (intent.language) draft.preferred_languages = [intent.language];
    if (intent.windows?.length) {
      // Current shape: each day carries its own specific time.
      draft.windows = intent.windows.map((w) => ({
        day_of_week: w.day, start_time: w.start, end_time: w.end, flexibility: "flexible",
      }));
    } else if (Array.isArray(intent.days) && intent.days.length && intent.from && intent.to) {
      // Legacy shape (pre-login sign-up flow): several days sharing one band.
      draft.windows = intent.days.map((n) => ({
        day_of_week: n, start_time: intent.from!, end_time: intent.to!, flexibility: "flexible",
      }));
    }
    return draft;
  }, []);
}

export function Requirements() {
  const qc = useQueryClient();
  const incomingIntent = useIncomingIntent();
  const [formOpen, setFormOpen] = useState(() => Boolean(incomingIntent));
  const [editing, setEditing] = useState<StudentRequirement | null>(null);
  const [offlineNotice, setOfflineNotice] = useState(false);

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

      {offlineNotice && (
        <div className="u-alert u-alert-warn items-center justify-between">
          <span>
            <strong>Finding an in-person teacher usually takes a little longer.</strong>{" "}
            We start with the nearest match and widen the search if needed.
          </span>
          <button type="button" className="u-btn-ghost u-btn-sm" onClick={() => setOfflineNotice(false)} aria-label="Dismiss">
            ✕
          </button>
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
            <RequirementCard key={r.id} r={r} onWithdraw={() => withdraw(r)} onEdit={() => setEditing(r)} />
          ))}
        </div>
      )}

      {formOpen && (
        <RequirementForm
          initial={incomingIntent}
          onClose={() => setFormOpen(false)}
          onSaved={(createdMode) => {
            setFormOpen(false);
            setOfflineNotice(createdMode === "offline" || createdMode === "both");
            qc.invalidateQueries({ queryKey: ["requirements"] });
          }}
        />
      )}

      {editing && (
        <RequirementForm
          requirementId={editing.id}
          initial={draftFromRequirement(editing)}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            qc.invalidateQueries({ queryKey: ["requirements"] });
          }}
        />
      )}
    </div>
  );
}

function RequirementCard({
  r, onWithdraw, onEdit,
}: {
  r: StudentRequirement;
  onWithdraw: () => void;
  onEdit: () => void;
}) {
  const open = r.status === "open";
  // Editable regardless of status - "matched" flips the moment a teacher
  // is merely soft-matched, long before anyone actually unlocks the
  // student's contact details. That unlock is the real lock.
  const editable = !r.has_unlocked_lead;
  const budgetRange = moneyRange(r.budget_min, r.budget_max);
  const budget = budgetRange ? `${budgetRange} / mo` : "Any";

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
        <Cell label="Language" value={languageLabel(r.no_language_preference, r.preferred_languages)} />
        <Cell label="Where" value={r.city?.name ?? (r.teaching_mode === "online" ? "Online" : "—")} />
        <Cell label="Posted" value={new Date(r.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} />
      </dl>

      <div className="mt-auto flex gap-2 border-t border-ink-200 pt-3">
        <a href={`/student/requirements/${r.id}/`} className="u-btn-secondary u-btn-sm flex-1">Open</a>
        {editable && (
          <button type="button" className="u-btn-ghost u-btn-sm" onClick={onEdit}>
            Edit
          </button>
        )}
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
