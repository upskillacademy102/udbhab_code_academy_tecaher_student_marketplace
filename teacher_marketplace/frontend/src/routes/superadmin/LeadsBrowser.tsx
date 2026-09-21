import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { StudentLeadQualityRating, StudentLeadQualitySummary, TeacherLeadReview } from "@/lib/types";

const VERDICT_BADGE: Record<string, string> = {
  genuine: "u-badge u-badge-pine",
  unreachable: "u-badge u-badge-marigold",
  fake: "u-badge u-badge-danger",
};

function VerdictBadge({ verdict }: { verdict: string }) {
  return <span className={VERDICT_BADGE[verdict] ?? "u-badge u-badge-ink"}>{verdict}</span>;
}

/**
 * Two ways to look at the same lead-quality data teachers submit after
 * unlocking a lead: grouped by the student who posted it (genuine/
 * unreachable/fake counts — where the fake-lead reports panel's numbers
 * come from), or by the teacher who rated it (with an offer-vs-pooled-
 * enquiry badge, since a direct "Learn with this teacher" pick behaves
 * differently from the ordinary matching cascade).
 */
export function LeadsBrowser() {
  const [tab, setTab] = useState<"students" | "teachers">("students");

  return (
    <div className="flex flex-col gap-6">
      <h1 className="u-h2">Leads &amp; requirements</h1>
      <div className="flex gap-1.5">
        <button type="button" className="u-chip u-chip-sm" aria-pressed={tab === "students"} onClick={() => setTab("students")}>
          By student
        </button>
        <button type="button" className="u-chip u-chip-sm" aria-pressed={tab === "teachers"} onClick={() => setTab("teachers")}>
          By teacher
        </button>
      </div>
      {tab === "students" ? <ByStudentTab /> : <ByTeacherTab />}
    </div>
  );
}

function ByStudentTab() {
  const [expanded, setExpanded] = useState<string | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["ops-students-lead-quality"],
    queryFn: () => api.get<{ results: StudentLeadQualitySummary[]; count: number }>("/ops/students-lead-quality/"),
  });
  const items = data?.results ?? [];

  const detail = useQuery({
    queryKey: ["ops-students-lead-quality", "detail", expanded],
    queryFn: () =>
      api.get<{ results: StudentLeadQualityRating[]; count: number }>("/ops/students-lead-quality/", {
        params: { student_id: expanded ?? undefined },
      }),
    enabled: !!expanded,
  });

  if (isError) {
    return (
      <div className="u-alert u-alert-error items-center justify-between">
        <span>{(error as { message?: string })?.message ?? "Couldn't load this list."}</span>
        <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-14 animate-pulse rounded-xl bg-ink-100" />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return <div className="u-card p-6 text-center text-ink-500">No lead-quality ratings recorded yet.</div>;
  }

  return (
    <div className="u-card overflow-hidden">
      <table className="w-full text-left text-[0.875rem]">
        <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
          <tr>
            <th className="px-4 py-2.5">Student</th>
            <th className="px-4 py-2.5">Total</th>
            <th className="px-4 py-2.5">Genuine</th>
            <th className="px-4 py-2.5">Unreachable</th>
            <th className="px-4 py-2.5">Fake</th>
            <th className="px-4 py-2.5">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-100">
          {items.map((row) => (
            <Fragment key={row.student_id}>
              <tr
                className="cursor-pointer hover:bg-paper-sunk/60"
                onClick={() => setExpanded(expanded === row.student_id ? null : row.student_id)}
              >
                <td className="px-4 py-3">
                  <p className="font-medium text-ink-900">{row.student_name || "(no name)"}</p>
                  <p className="text-ink-500">{row.student_email}</p>
                </td>
                <td className="px-4 py-3 text-ink-600">{row.total_ratings}</td>
                <td className="px-4 py-3 text-ink-600">{row.genuine}</td>
                <td className="px-4 py-3 text-ink-600">{row.unreachable}</td>
                <td className="px-4 py-3 text-ink-600">{row.fake}</td>
                <td className="px-4 py-3">
                  {row.sanction ? (
                    <span className="u-badge u-badge-danger">Banned</span>
                  ) : row.account_active === false ? (
                    <span className="u-badge u-badge-ink">Inactive</span>
                  ) : (
                    <span className="u-badge u-badge-pine">Active</span>
                  )}
                </td>
              </tr>
              {expanded === row.student_id && (
                <tr>
                  <td colSpan={6} className="bg-paper-sunk/40 px-4 py-3">
                    {detail.isLoading ? (
                      <div className="h-10 animate-pulse rounded-lg bg-ink-100" />
                    ) : detail.isError ? (
                      <p className="text-danger">
                        {(detail.error as { message?: string })?.message ?? "Couldn't load this student's ratings."}{" "}
                        <button type="button" className="underline" onClick={() => detail.refetch()}>Try again</button>
                      </p>
                    ) : (detail.data?.results.length ?? 0) === 0 ? (
                      <p className="text-ink-500">No individual ratings found.</p>
                    ) : (
                      <ul className="flex flex-col gap-2">
                        {detail.data!.results.map((r) => (
                          <li key={r.id} className="flex flex-wrap items-center gap-2">
                            <VerdictBadge verdict={r.verdict} />
                            <span className="text-ink-700">{r.teacher_name}</span>
                            <span className="text-ink-400">· {new Date(r.created_at).toLocaleString()}</span>
                            {r.note && <span className="text-ink-500">— {r.note}</span>}
                            {r.clawed_back && <span className="u-badge u-badge-marigold">Refunded</span>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ByTeacherTab() {
  const [verdict, setVerdict] = useState("");
  const [search, setSearch] = useState("");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["ops-teacher-lead-reviews", verdict],
    queryFn: () =>
      api.get<{ results: TeacherLeadReview[]; count: number }>("/ops/teacher-lead-reviews/", {
        params: { verdict: verdict || undefined },
      }),
  });
  const items = (data?.results ?? []).filter((r) => {
    if (!search.trim()) return true;
    const s = search.toLowerCase();
    return r.teacher_name.toLowerCase().includes(s) || r.teacher_email.toLowerCase().includes(s);
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-1.5">
          {["", "genuine", "unreachable", "fake"].map((v) => (
            <button
              key={v || "all"}
              type="button"
              className="u-chip u-chip-sm"
              aria-pressed={verdict === v}
              onClick={() => setVerdict(v)}
            >
              {v ? v[0]!.toUpperCase() + v.slice(1) : "All"}
            </button>
          ))}
        </div>
        <input
          className="u-input w-56"
          placeholder="Filter by teacher name/email"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? "Couldn't load this list."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {!isError && (isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-xl bg-ink-100" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="u-card p-6 text-center text-ink-500">No ratings match this filter.</div>
      ) : (
        <div className="u-card overflow-hidden">
          <table className="w-full text-left text-[0.875rem]">
            <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
              <tr>
                <th className="px-4 py-2.5">Teacher</th>
                <th className="px-4 py-2.5">Student</th>
                <th className="px-4 py-2.5">Verdict</th>
                <th className="px-4 py-2.5">Lead type</th>
                <th className="px-4 py-2.5">When</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {items.map((r) => (
                <tr key={r.id}>
                  <td className="px-4 py-3">
                    <p className="font-medium text-ink-900">{r.teacher_name}</p>
                    <p className="text-ink-500">{r.teacher_email}</p>
                  </td>
                  <td className="px-4 py-3 text-ink-600">{r.student_name}</td>
                  <td className="px-4 py-3"><VerdictBadge verdict={r.verdict} /></td>
                  <td className="px-4 py-3">
                    <span className={r.is_direct_offer ? "u-badge u-badge-marigold" : "u-badge u-badge-ink"}>
                      {r.is_direct_offer ? "Direct offer" : "Pooled enquiry"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-ink-500">{new Date(r.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
