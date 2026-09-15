import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Lead } from "@/lib/types";
import { AllowanceBar, useAllowance } from "@/components/Allowance";
import { confirmAction, money, titleCase, toast } from "@/lib/ui";

/**
 * One enquiry, and the decision to spend an unlock on it.
 *
 * Unlocking costs real money, so it is a deliberate, confirmed action with
 * the price stated before the click — never a one-tap surprise. A surprise
 * spend is a support ticket and a refund request.
 *
 * After unlocking, rating the lead is asked for directly rather than left to
 * a banner elsewhere: telling us which enquiries were genuine is the only
 * signal that keeps fake ones out of every teacher's list, and the moment
 * right after contact is when the teacher actually knows.
 */

const VERDICTS = [
  { id: "genuine", label: "Genuine enquiry", tone: "good" },
  { id: "fake", label: "Fake or spam", tone: "bad" },
  { id: "unreachable", label: "Couldn't reach them", tone: "neutral" },
] as const;

// Traffic-light colors, deliberately louder than this design system's usual
// one-accent-per-screen rule (see static/src/app.css) — this decision feeds
// fake-lead detection and refunds, so it needs to read at a glance, not blend
// into the page like a routine chip.
const VERDICT_TONE: Record<string, string> = {
  good: "border-emerald-500 bg-emerald-50 text-emerald-800 hover:bg-emerald-100 aria-pressed:bg-emerald-500 aria-pressed:text-white",
  bad: "border-rose-500 bg-rose-50 text-rose-800 hover:bg-rose-100 aria-pressed:bg-rose-500 aria-pressed:text-white",
  neutral: "border-ink-300 bg-ink-100 text-ink-700 hover:bg-ink-200 aria-pressed:bg-ink-500 aria-pressed:text-white",
};

export function LeadDetail() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const { quota } = useAllowance();
  const [unlocking, setUnlocking] = useState(false);

  const { data: lead, isLoading, isError, error } = useQuery<Lead>({
    queryKey: ["lead", id],
    queryFn: () => api.get<Lead>(`/leads/${id}/`),
  });

  const remaining = quota?.remaining_free_leads ?? 0;

  async function unlock() {
    if (!lead) return;
    const ok = await confirmAction({
      title: "Unlock this student's contact details?",
      message:
        remaining > 0
          ? `This uses 1 of your ${remaining} remaining ${remaining === 1 ? "unlock" : "unlocks"}.`
          : "You're out of plan unlocks, so this will use a top-up unlock.",
      confirmLabel: "Unlock it",
    });
    if (!ok) return;

    setUnlocking(true);
    try {
      await api.post("/leads/unlock/", { lead_id: id });
      toast("success", "Unlocked. Their details are below.");
      qc.invalidateQueries({ queryKey: ["lead", id] });
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["quota"] });
      qc.invalidateQueries({ queryKey: ["teacher-dashboard"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't unlock that.");
    } finally {
      setUnlocking(false);
    }
  }

  if (isLoading) return <div className="h-96 animate-pulse rounded-2xl bg-ink-100" />;

  if (isError || !lead) {
    const notFound = (error as { status?: number })?.status === 404;
    return (
      <section className="u-card flex flex-col items-center gap-4 px-6 py-14 text-center">
        <h1 className="u-h3">{notFound ? "We can't find that enquiry" : "Couldn't load that enquiry"}</h1>
        <Link to="/teacher/leads/" className="u-btn-primary">Back to enquiries</Link>
      </section>
    );
  }

  const unlocked = Boolean(lead.contact_unlocked);
  const budget =
    lead.budget_min || lead.budget_max ? `${money(lead.budget_min) ?? "—"} – ${money(lead.budget_max) ?? "—"}` : "Not said";

  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <Link to="/teacher/leads/" className="u-link -mt-1 text-[0.875rem]">← All enquiries</Link>

      {!unlocked && <AllowanceBar compact />}

      <section className="u-card u-card-pad">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="u-h2">{lead.subject_name ?? "Enquiry"}</h1>
            <p className="u-fine mt-1">
              {[titleCase(lead.teaching_mode ?? ""), lead.city_name].filter(Boolean).join(" · ") || "—"}
            </p>
          </div>
          <span className={unlocked ? "u-badge u-badge-pine" : "u-badge u-badge-marigold"}>
            {unlocked ? "Unlocked" : "Locked"}
          </span>
        </div>

        <dl className="mt-5 grid gap-x-6 gap-y-4 sm:grid-cols-2">
          <Row label="Budget" value={budget} />
          <Row label="Came in" value={new Date(lead.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "long" })} />
          {lead.preferred_timing && <Row label="Timing" value={lead.preferred_timing} />}
          {lead.status && <Row label="Status" value={titleCase(lead.status)} />}
        </dl>

        {lead.description && (
          <div className="mt-5 border-t border-ink-200 pt-4">
            <h2 className="u-eyebrow">What they said</h2>
            <p className="u-body mt-2 whitespace-pre-line text-ink-700">{lead.description}</p>
          </div>
        )}
      </section>

      {/* ---- Contact ---- */}
      <section className="u-card u-card-pad">
        <h2 className="u-h3">{unlocked ? "Their details" : "Contact details"}</h2>

        {unlocked ? (
          <dl className="mt-4 flex flex-col gap-3">
            <ContactRow label="Name" value={lead.student_name} />
            <ContactRow label="Phone" value={lead.student_mobile} href={lead.student_mobile ? `tel:${lead.student_mobile}` : undefined} />
            <ContactRow label="Email" value={lead.student_email} href={lead.student_email ? `mailto:${lead.student_email}` : undefined} />
            <p className="u-fine mt-1">Get in touch soon — students usually pick whoever replies first.</p>
          </dl>
        ) : (
          <>
            <p className="u-body mt-2 text-ink-600">
              Unlock to see their name, phone and email. One unlock — taken from your plan first, then any top-ups.
            </p>
            <button
              type="button"
              className="u-btn-primary u-btn-lg mt-4 w-full"
              onClick={unlock}
              data-loading={unlocking || undefined}
              disabled={unlocking}
            >
              Unlock for 1 unlock
            </button>
            <p className="u-fine mt-2 text-center">
              {remaining > 0
                ? `${remaining} left on your plan this month`
                : "No plan unlocks left — this uses a top-up"}
            </p>
          </>
        )}
      </section>

      {unlocked && <RateLead leadId={id} existing={lead.my_rating ?? null} />}
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

function ContactRow({ label, value, href }: { label: string; value?: string | null; href?: string }) {
  if (!value) return null;
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-ink-200 bg-paper-sunk px-4 py-3">
      <span className="text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">{label}</span>
      {href ? (
        <a href={href} className="u-link text-[0.9375rem]">{value}</a>
      ) : (
        <span className="text-[0.9375rem] font-semibold text-ink-900">{value}</span>
      )}
    </div>
  );
}

function RateLead({ leadId, existing }: { leadId: string; existing: string | null }) {
  const qc = useQueryClient();
  const [verdict, setVerdict] = useState<string | null>(existing);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(Boolean(existing));

  async function send(v: string) {
    setVerdict(v);
    setSaving(true);
    try {
      await api.post(`/leads/${leadId}/rate/`, { verdict: v, note });
      setDone(true);
      toast("success", "Thanks — that helps keep fake enquiries out.");
      qc.invalidateQueries({ queryKey: ["lead", leadId] });
      qc.invalidateQueries({ queryKey: ["teacher-dashboard"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't save that.");
    } finally {
      setSaving(false);
    }
  }

  if (done) {
    return (
      <section className="u-card u-card-pad border-pine-300 bg-pine-50">
        <p className="text-[0.9375rem] font-semibold text-pine-900">Thanks for rating this one.</p>
        <p className="u-fine mt-1">It's what keeps fake enquiries out of everyone's list.</p>
      </section>
    );
  }

  return (
    <section className="u-card u-card-pad border-2 border-marigold-400 bg-marigold-50">
      <h2 className="u-h3">Was this a real enquiry?</h2>
      <p className="u-body mt-1.5 text-ink-600">
        Every teacher is asked. It's the only way we catch fake enquiries — and you don't pay for the ones we catch.
        You must rate every lead you unlock before you can keep browsing.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        {VERDICTS.map((v) => (
          <button
            key={v.id}
            type="button"
            className={`min-h-[44px] flex-1 rounded-xl border-2 px-4 text-[0.9375rem] font-semibold shadow-soft transition ${VERDICT_TONE[v.tone]}`}
            aria-pressed={verdict === v.id}
            disabled={saving}
            onClick={() => send(v.id)}
          >
            {v.label}
          </button>
        ))}
      </div>
      <textarea
        className="u-textarea mt-3"
        rows={2}
        maxLength={500}
        placeholder="Anything else? (optional)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
    </section>
  );
}
