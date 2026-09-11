import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Quota, TeacherDashboard } from "@/lib/types";

/**
 * How many unlocks are left, and when they vanish.
 *
 * Unused unlocks do not carry over, so this is a loss, not a balance — and
 * losses weigh about twice what equivalent gains do. The design says so
 * plainly rather than burying it: the number is large, the reset is next to
 * it, and the "they don't roll over" line is never hidden.
 *
 * The word "token" must never appear. TOKEN_SYSTEM_ENABLED is off, so the
 * economy a teacher sees is plan unlocks plus top-up packs.
 */

export function useAllowance() {
  const quota = useQuery({
    queryKey: ["quota"],
    queryFn: () => api.get<Quota>("/subscriptions/quota/", { silent: true }),
    retry: false,
  });
  const dash = useQuery({
    queryKey: ["teacher-dashboard"],
    queryFn: () => api.get<TeacherDashboard>("/dashboard/", { silent: true }),
    retry: false,
  });
  return { quota: quota.data, dash: dash.data, isLoading: quota.isLoading || dash.isLoading };
}

function resetLine(days: number | undefined): string {
  if (days === undefined || days === null) return "";
  if (days <= 0) return "resets today";
  if (days === 1) return "resets tomorrow";
  return `resets in ${days} days`;
}

export function AllowanceBar({ compact = false }: { compact?: boolean }) {
  const { quota, dash, isLoading } = useAllowance();

  if (isLoading) return <div className="h-24 animate-pulse rounded-2xl bg-ink-100" />;
  if (!quota) return null;

  const left = quota.remaining_free_leads ?? 0;
  const total = quota.total_free_leads ?? 0;
  const days = quota.days_until_reset;
  const extra = Number(dash?.extra_unlocks ?? 0);
  const none = left === 0;
  // Two days out with unlocks still unspent is the moment the loss is real.
  const expiringSoon = !none && typeof days === "number" && days <= 2;

  return (
    <section
      className={
        "u-card u-card-pad " +
        (none ? "border-marigold-400 bg-marigold-50" : expiringSoon ? "border-marigold-300" : "")
      }
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-display text-3xl font-bold leading-none tracking-tight text-ink-900">
            <span className="tabular-nums">{left}</span>
            <span className="text-ink-500"> of </span>
            <span className="tabular-nums">{total}</span>
            <span className="ml-2 font-sans text-[0.9375rem] font-semibold text-ink-700">
              {total === 1 ? "unlock" : "unlocks"} left
            </span>
          </p>
          <p className="u-fine mt-1.5">
            {resetLine(days)}
            {total > 0 && " · unused ones don't roll over"}
          </p>
          {extra > 0 && (
            <p className="mt-1.5 text-[0.8125rem] font-medium text-pine-700">
              + {extra} extra {extra === 1 ? "unlock" : "unlocks"} · these never expire
            </p>
          )}
        </div>

        {none && (
          <a href="/teacher/plan/" className="u-btn-primary shrink-0">
            Get more
          </a>
        )}
      </div>

      {expiringSoon && !compact && (
        <p className="mt-3 rounded-xl bg-marigold-100 px-3.5 py-2.5 text-[0.875rem] text-marigold-900">
          <strong className="font-semibold">
            {left} {left === 1 ? "unlock" : "unlocks"} {resetLine(days)}.
          </strong>{" "}
          Spend them on your strongest matches below.
        </p>
      )}
    </section>
  );
}
