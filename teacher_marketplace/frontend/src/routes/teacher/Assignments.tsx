import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type { Lead } from "@/lib/types";
import { titleCase } from "@/lib/ui";

/**
 * Offers - direct "Learn with this teacher" picks only.
 *
 * A student chose THIS teacher specifically, from that teacher's own
 * profile, skipping the general matching pool entirely. Unlike an ordinary
 * lead, an offer never expires - the gold styling here (and the nav-glow
 * while any are pending) is what should catch a teacher's eye, not a
 * countdown, since there's nothing to count down to.
 *
 * Unlocking/rejecting/reviewing an offer goes through the exact same
 * LeadDetail page as any other lead - no separate accept/pass flow here
 * any more, since unlocking now doubles as accepting.
 */
export function Assignments() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["offers"],
    queryFn: () => api.list<Lead>("/leads/offers/"),
  });

  const items = data?.items ?? [];

  return (
    <div className="flex flex-col gap-5">
      <h1 className="u-h2">
        {isLoading ? "Loading…" : items.length ? `${items.length} offer${items.length === 1 ? "" : "s"} for you` : "Offers"}
      </h1>

      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => <div key={i} className="h-40 animate-pulse rounded-2xl bg-ink-100" />)}
        </div>
      )}

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? "Couldn't load your offers."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <section className="u-card flex flex-col items-center gap-3 px-6 py-14 text-center">
          <h2 className="u-h3">No offers right now</h2>
          <p className="u-body max-w-prose text-ink-600">
            When a student picks you directly from your profile — instead of the general matching pool — it lands
            here. Offers never expire, but you still spend 1 unlock to see their details, same as any lead.
          </p>
        </section>
      )}

      {items.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          {items.map((l, i) => (
            <Link
              key={l.id}
              to={`/teacher/leads/${l.id}/`}
              className="u-stagger-item flex flex-col gap-3 rounded-2xl border-2 border-marigold-400 bg-marigold-50 p-5 shadow-lift transition duration-150 ease-enter hover:-translate-y-px hover:shadow-raise"
              style={{ "--d": `${Math.min(i, 7) * 30}ms` } as React.CSSProperties}
            >
              <div className="flex items-start justify-between gap-3">
                <h2 className="min-w-0 truncate text-[1rem] font-semibold text-ink-900">
                  {l.subject_name ?? "Offer"}
                </h2>
                <span className="u-badge u-badge-marigold shrink-0">
                  {l.contact_unlocked ? "Unlocked" : "New"}
                </span>
              </div>

              <p className="u-fine">
                {[titleCase(l.teaching_mode ?? ""), l.city_name].filter(Boolean).join(" · ") || "—"} — chose you
                directly
              </p>

              <div className="mt-auto flex items-center justify-between border-t border-marigold-200 pt-3">
                <span className="u-fine">Never expires</span>
                <span className="inline-flex items-center gap-1 text-[0.8125rem] font-semibold text-pine-700">
                  Open
                  <span aria-hidden="true">→</span>
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
