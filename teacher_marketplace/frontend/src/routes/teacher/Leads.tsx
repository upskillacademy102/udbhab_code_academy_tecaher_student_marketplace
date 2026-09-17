import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type { Lead } from "@/lib/types";
import { AllowanceBar } from "@/components/Allowance";
import { moneyRange, titleCase } from "@/lib/ui";

/**
 * Student leads matched to this teacher.
 *
 * The allowance sits at the top of this page on purpose: every card below it
 * costs one, so the budget belongs in view while the choice is being made,
 * not one page away.
 *
 * Contact details stay hidden until unlocked — that is the product, not a
 * dark pattern — so each card shows everything needed to judge the lead
 * (subject, mode, budget, when) and nothing that identifies the student.
 */
export function Leads() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["leads"],
    queryFn: () => api.list<Lead>("/leads/"),
  });

  const items = data?.items ?? [];
  const locked = items.filter((l) => !l.contact_unlocked);
  const unlocked = items.filter((l) => l.contact_unlocked);

  return (
    <div className="flex flex-col gap-6">
      <AllowanceBar />

      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-40 animate-pulse rounded-2xl bg-ink-100" />)}
        </div>
      )}

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? "Couldn't load your leads."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <section className="u-card flex flex-col items-center gap-4 px-6 py-14 text-center">
          <h1 className="u-h3">No leads yet</h1>
          <p className="u-body max-w-prose text-ink-600">
            Students get matched to you on subject, language and the hours you've set as free. The more hours you
            set, the more students can reach you.
          </p>
          <a href="/teacher/availability/" className="u-btn-primary">Set your hours</a>
        </section>
      )}

      {locked.length > 0 && (
        <section className="flex flex-col gap-4">
          <h1 className="u-h2">{locked.length} waiting for you</h1>
          <div className="grid gap-4 sm:grid-cols-2">
            {locked.map((l, i) => <LeadCard key={l.id} lead={l} index={i} />)}
          </div>
        </section>
      )}

      {unlocked.length > 0 && (
        <section className="flex flex-col gap-4">
          <h2 className="u-h3">Already unlocked</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {unlocked.map((l, i) => <LeadCard key={l.id} lead={l} index={i} />)}
          </div>
        </section>
      )}
    </div>
  );
}

function LeadCard({ lead: l, index }: { lead: Lead; index: number }) {
  const budgetRange = moneyRange(l.budget_min, l.budget_max);
  const budget = budgetRange ? `${budgetRange} / mo` : "Not said";
  const open = !l.contact_unlocked;

  return (
    <Link
      to={`/teacher/leads/${l.id}/`}
      className="u-stagger-item group flex flex-col gap-3 rounded-2xl border-[1.5px] border-ink-300 bg-paper p-5 shadow-lift transition duration-150 ease-enter hover:-translate-y-px hover:border-pine-400 hover:shadow-raise"
      style={{ "--d": `${Math.min(index, 7) * 30}ms` } as React.CSSProperties}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-[1rem] font-semibold text-ink-900">{l.subject_name ?? "Lead"}</h3>
          <p className="u-fine mt-0.5">
            {[titleCase(l.teaching_mode ?? ""), l.city_name].filter(Boolean).join(" · ") || "—"}
          </p>
        </div>
        {open ? (
          <span className="u-badge u-badge-marigold shrink-0">New</span>
        ) : (
          <span className="u-badge u-badge-pine shrink-0">Unlocked</span>
        )}
      </div>

      {Boolean(l.unlocked_count) && (
        <p className="u-badge u-badge-marigold w-fit text-[0.75rem]">
          {l.unlocked_count} teacher{l.unlocked_count === 1 ? "" : "s"} unlocked this
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-[0.8125rem]">
        <div>
          <dt className="text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">Budget</dt>
          <dd className="mt-0.5 font-medium tabular-nums text-ink-900">{budget}</dd>
        </div>
        <div>
          <dt className="text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">Came in</dt>
          <dd className="mt-0.5 font-medium text-ink-900">
            {new Date(l.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
          </dd>
        </div>
      </dl>

      <div className="mt-auto flex items-center justify-between border-t border-ink-200 pt-3">
        <span className="u-fine">{open ? "Contact details hidden" : (l.student_name ?? "Contact unlocked")}</span>
        <span className="inline-flex items-center gap-1 text-[0.8125rem] font-semibold text-pine-700">
          {open ? "See it" : "Open"}
          <span aria-hidden="true" className="transition group-hover:translate-x-0.5">→</span>
        </span>
      </div>
    </Link>
  );
}
