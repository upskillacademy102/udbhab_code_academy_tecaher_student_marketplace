import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import type { Lead, TeacherProfile } from "@/lib/types";
import { AllowanceBar, useAllowance } from "@/components/Allowance";
import { replayTeacherIntent } from "@/lib/replayIntent";
import { titleCase } from "@/lib/ui";

function firstNameLastInitial(name?: string | null): string | null {
  if (!name || name === "********") return null;
  const parts = name.trim().split(/\s+/);
  const first = parts[0];
  if (!first) return null;
  if (parts.length === 1) return first;
  const last = parts[parts.length - 1] ?? "";
  return last ? `${first} ${last[0]}.` : first;
}

function relativeTime(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function waLink(mobile?: string | null): string | null {
  if (!mobile) return null;
  const digits = mobile.replace(/\D/g, "");
  if (!digits) return null;
  return `https://wa.me/${digits.length === 10 ? "91" + digits : digits}`;
}

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
    if (!p.hourly_rate && !p.monthly_rate) gaps.push("your rate");
    if (!p.subjects?.length) gaps.push("subjects");
    if (!p.languages?.length) gaps.push("languages");
  }
  const notVerified = p && !p.is_verified;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="u-badge u-badge-pine w-fit">Teacher Portal</span>
        <div className="flex flex-wrap items-center gap-2">
          <a href="/teacher/settings/" className="u-btn-secondary u-btn-sm">Preferences</a>
          <a href="/teacher/plan/" className="u-btn-primary u-btn-sm inline-flex items-center gap-1.5">
            <BoltIcon /> Get more unlocks
          </a>
        </div>
      </div>

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
              body="Telling us which leads were genuine is how we keep fake ones out of your list."
              action={{ label: "Rate them", href: "/teacher/leads/" }} />
          )}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Waiting for you" value={fresh.length} hint="not unlocked yet" icon={<HourglassIcon />} tone="marigold" />
        <Stat label="Unlocked" value={Number(dash?.unlocked_leads ?? 0)} hint="all time" icon={<UnlockIcon />} tone="pine" />
        <Stat label="New today" value={Number(dash?.todays_leads ?? 0)} hint="matched to you" icon={<SparkIcon />} tone="ink" />
      </div>

      <section className="u-card overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-ink-200 px-5 py-4">
          <div className="flex items-center gap-2">
            <h2 className="u-h3">Latest leads</h2>
            {items.length > 0 && <span className="u-badge u-badge-pine">{items.length} active</span>}
          </div>
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
          <>
            <ul className="divide-y divide-ink-200">
              {items.slice(0, 5).map((l) => {
                const contact = firstNameLastInitial(l.student_name);
                const wa = l.contact_unlocked ? waLink(l.student_mobile) : null;
                return (
                  <li key={l.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <p className="truncate text-[0.9375rem] font-semibold text-ink-900">{l.subject_name ?? "Lead"}</p>
                        {l.contact_unlocked ? (
                          <span className="u-badge u-badge-pine shrink-0">Unlocked</span>
                        ) : (
                          <span className="u-badge u-badge-marigold shrink-0">New</span>
                        )}
                        {l.teaching_mode && <span className="u-badge u-badge-ink shrink-0 capitalize">{titleCase(l.teaching_mode)}</span>}
                      </div>
                      {l.description && (
                        <p className="u-fine mt-1 line-clamp-1 max-w-prose">{l.description}</p>
                      )}
                      <p className="u-fine mt-1 truncate text-ink-500">
                        Received {relativeTime(l.created_at)}
                        {contact && <> · Contact: {contact}</>}
                        {l.contact_unlocked ? " · Phone unlocked" : " · Contact hidden until unlocked"}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <Link to={`/teacher/leads/${l.id}/`} className="u-btn-secondary u-btn-sm">View details</Link>
                      {wa && (
                        <a href={wa} target="_blank" rel="noopener noreferrer"
                           className="u-btn-primary u-btn-sm inline-flex items-center gap-1.5">
                          <MessageIcon /> Message
                        </a>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
            <p className="border-t border-ink-200 px-5 py-3 text-[0.75rem] text-ink-400">
              Unlocked leads retain contact visibility indefinitely in your account history.
              <a href="/api/v1/leads/export/" className="u-link ml-1">Download CSV report</a>
            </p>
          </>
        )}
      </section>
    </div>
  );
}

const STAT_TONE: Record<string, string> = {
  marigold: "bg-marigold-100 text-marigold-800",
  pine: "bg-pine-100 text-pine-800",
  ink: "bg-ink-100 text-ink-600",
};

function Stat({
  label, value, hint, icon, tone,
}: {
  label: string;
  value: number;
  hint: string;
  icon?: React.ReactNode;
  tone?: "marigold" | "pine" | "ink";
}) {
  return (
    <div className="u-card u-card-pad relative">
      {icon && (
        <span className={`absolute right-4 top-4 grid h-7 w-7 place-items-center rounded-full ${STAT_TONE[tone ?? "ink"]}`}>
          {icon}
        </span>
      )}
      <p className="u-eyebrow">{label}</p>
      <p className="mt-1.5 font-display text-3xl font-bold tabular-nums leading-none text-ink-900">{value}</p>
      <p className="u-fine mt-1">{hint}</p>
    </div>
  );
}

/* ---------------- small inline icons ---------------- */

function BoltIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M9 1 3 9h4l-1 6 6-8H8l1-6Z" />
    </svg>
  );
}

function HourglassIcon() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M4 2h8M4 14h8M4.5 2c0 3 2.5 4 3.5 5-1 1-3.5 2-3.5 5M11.5 2c0 3-2.5 4-3.5 5 1 1 3.5 2 3.5 5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function UnlockIcon() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <rect x="3" y="7" width="10" height="7" rx="1.5" />
      <path d="M5.5 7V5a2.5 2.5 0 0 1 4.85-.85" strokeLinecap="round" />
    </svg>
  );
}

function SparkIcon() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 1.5 9.3 6l4.2.3-3.3 2.8 1 4.4L8 11l-3.2 2.5 1-4.4-3.3-2.8L6.7 6 8 1.5Z" />
    </svg>
  );
}

function MessageIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M2 3.5A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5v6A1.5 1.5 0 0 1 12.5 11H6l-3 3v-3H3.5A1.5 1.5 0 0 1 2 9.5v-6Z" />
    </svg>
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
