import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type { Lead, TeacherProfile } from "@/lib/types";
import { AllowanceBar, useAllowance } from "@/components/Allowance";
import { replayTeacherIntent } from "@/lib/replayIntent";
import { titleCase } from "@/lib/ui";

/**
 * The teacher's home.
 *
 * Ordered by what costs them something: the allowance first (unused unlocks
 * expire), then leads waiting, then anything blocking their visibility. A
 * profile-completeness meter only appears when the profile is actually
 * incomplete — a permanent "you're at 80%" bar is nagging, not information.
 */
export function TeacherDashboard() {
  const { dash } = useAllowance();
  const qc = useQueryClient();
  const replayed = useRef(false);

  // Sign-up collected subjects, ranked languages and hours before this
  // account existed. Turn them into real rows on the first authenticated
  // load, then refresh whatever depended on them. Guarded by a ref because
  // StrictMode runs effects twice in development.
  useEffect(() => {
    if (replayed.current) return;
    replayed.current = true;
    replayTeacherIntent().then((changed) => {
      if (!changed) return;
      qc.invalidateQueries({ queryKey: ["my-teacher-profile"] });
      qc.invalidateQueries({ queryKey: ["weekly-availability"] });
    });
  }, [qc]);

  const leads = useQuery({
    queryKey: ["leads"],
    queryFn: () => api.list<Lead>("/leads/"),
  });

  const profile = useQuery({
    queryKey: ["my-teacher-profile"],
    queryFn: async () => {
      try {
        return await api.get<TeacherProfile>("/teachers/profile/", { silent: true });
      } catch {
        return null;
      }
    },
    retry: false,
  });

  const items = leads.data?.items ?? [];
  const fresh = items.filter((l) => !l.contact_unlocked);
  const pendingRatings = Number(dash?.pending_rating_count ?? 0);
  const p = profile.data;

  const gaps: string[] = [];
  if (p) {
    if (!p.headline) gaps.push("a headline");
    if (!p.hourly_rate) gaps.push("your rate");
    if (!p.subjects?.length) gaps.push("subjects");
    if (!p.languages?.length) gaps.push("languages");
  }
  const notVerified = p && !p.is_verified;

  return (
    <div className="flex flex-col gap-6">
      <AllowanceBar />

      {/* Anything actually blocking them comes before anything nice to know. */}
      {(notVerified || gaps.length > 0 || pendingRatings > 0) && (
        <div className="flex flex-col gap-3">
          {notVerified && (
            <Banner tone="warn"
              title="You're not in search results yet"
              body="Students only see verified teachers. Finish verification and you'll start getting matched."
              action={{ label: "Get verified", href: "/teacher/profile/" }} />
          )}
          {gaps.length > 0 && (
            <Banner tone="info"
              title={`Add ${gaps.slice(0, 2).join(" and ")} to your profile`}
              body="A fuller profile matches more students and ranks higher in search."
              action={{ label: "Finish it", href: "/teacher/profile/" }} />
          )}
          {pendingRatings > 0 && (
            <Banner tone="info"
              title={`Rate ${pendingRatings} ${pendingRatings === 1 ? "lead" : "leads"} you unlocked`}
              body="Telling us which enquiries were genuine is how we keep fake ones out of your list."
              action={{ label: "Rate them", href: "/teacher/leads/" }} />
          )}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Waiting for you" value={fresh.length} hint="not unlocked yet" />
        <Stat label="Unlocked" value={Number(dash?.unlocked_leads ?? 0)} hint="all time" />
        <Stat label="New today" value={Number(dash?.todays_leads ?? 0)} hint="matched to you" />
      </div>

      <section className="u-card overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-ink-200 px-5 py-4">
          <h2 className="u-h3">Latest enquiries</h2>
          <Link to="/teacher/leads/" className="u-link text-[0.875rem]">See all →</Link>
        </div>

        {leads.isLoading && (
          <div className="flex flex-col gap-2 p-4">
            {Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-16 animate-pulse rounded-xl bg-ink-100" />)}
          </div>
        )}

        {!leads.isLoading && items.length === 0 && (
          <div className="px-6 py-12 text-center">
            <h3 className="u-h3">Nothing yet</h3>
            <p className="u-body mx-auto mt-2 max-w-prose text-ink-600">
              When a student asks for what you teach, at a time you're free, it lands here. Setting your
              availability is the fastest way to get matched.
            </p>
            <a href="/teacher/availability/" className="u-btn-primary mt-4">Set your hours</a>
          </div>
        )}

        {items.length > 0 && (
          <ul className="divide-y divide-ink-200">
            {items.slice(0, 5).map((l) => (
              <li key={l.id}>
                <Link to={`/teacher/leads/${l.id}/`} className="flex items-center gap-3 px-5 py-3.5 transition hover:bg-pine-50">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[0.9375rem] font-semibold text-ink-900">{l.subject_name ?? "Enquiry"}</p>
                    <p className="u-fine mt-0.5 truncate">
                      {[titleCase(l.teaching_mode ?? ""), l.city_name].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                  {l.contact_unlocked ? (
                    <span className="u-badge u-badge-pine shrink-0">Unlocked</span>
                  ) : (
                    <span className="u-badge u-badge-marigold shrink-0">New</span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: number; hint: string }) {
  return (
    <div className="u-card u-card-pad">
      <p className="u-eyebrow">{label}</p>
      <p className="mt-1.5 font-display text-3xl font-bold tabular-nums leading-none text-ink-900">{value}</p>
      <p className="u-fine mt-1">{hint}</p>
    </div>
  );
}

function Banner({
  tone, title, body, action,
}: {
  tone: "warn" | "info";
  title: string;
  body: string;
  action: { label: string; href: string };
}) {
  return (
    <div
      className={
        "u-card flex flex-wrap items-center justify-between gap-3 p-4 " +
        (tone === "warn" ? "border-marigold-400 bg-marigold-50" : "border-pine-300 bg-pine-50")
      }
    >
      <div className="min-w-0">
        <p className="text-[0.9375rem] font-semibold text-ink-900">{title}</p>
        <p className="u-fine mt-0.5">{body}</p>
      </div>
      <a href={action.href} className="u-btn-secondary u-btn-sm shrink-0">{action.label}</a>
    </div>
  );
}
