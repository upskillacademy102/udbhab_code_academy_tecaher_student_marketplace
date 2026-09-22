import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AdminUser } from "@/lib/types";
import { confirmAction, toast } from "@/lib/ui";

// Same reason list as UserReportReason (apps.trust.models) — mirrors
// routes/student/TeacherDetail.tsx's SafetyBox, the existing report flow.
const REPORT_REASONS = [
  { id: "off_platform", label: "Asked to pay or chat off-platform" },
  { id: "spam", label: "Spam or scam" },
  { id: "abuse", label: "Abusive behaviour" },
  { id: "impersonation", label: "Fake profile" },
  { id: "no_show", label: "Didn't show up" },
  { id: "other", label: "Something else" },
] as const;

/**
 * Shared detail shell for the Learning Partner's Student/Teacher screens.
 * Read-only (no edit, no ban) — the only action available is "request a
 * ban", which reuses the existing report -> Super-Admin-review-queue flow
 * (POST /safety/report/, already granted to role=admin) rather than a new
 * ban-request model.
 */
export function LPUserDetail({
  endpointBase, backTo, backLabel,
}: {
  endpointBase: string;
  backTo: string;
  backLabel: string;
}) {
  const { id } = useParams<{ id: string }>();
  const user = useQuery({
    queryKey: [endpointBase, id],
    queryFn: () => api.get<AdminUser>(`${endpointBase}${id}/`),
    enabled: !!id,
  });

  if (user.isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <div className="h-8 w-48 animate-pulse rounded-lg bg-ink-100" />
        <div className="h-32 animate-pulse rounded-xl bg-ink-100" />
      </div>
    );
  }

  if (user.isError || !user.data) {
    return (
      <div className="u-alert u-alert-error items-center justify-between">
        <span>{(user.error as { message?: string })?.message ?? "Couldn't load this account."}</span>
        <Link to={backTo} className="u-btn-secondary u-btn-sm">{backLabel}</Link>
      </div>
    );
  }

  const u = user.data;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to={backTo} className="text-[0.8125rem] text-ink-500 hover:underline">← {backLabel}</Link>
        <h1 className="u-h2 mt-1">{u.full_name || "(no name)"}</h1>
      </div>

      <div className="u-card grid grid-cols-1 gap-4 p-4 sm:grid-cols-2">
        <Field label="Email" value={u.email} />
        <Field label="Mobile" value={u.mobile} />
        <Field label="Status" value={u.is_active ? "Active" : "Inactive"} />
        <Field label="Email verified" value={u.is_email_verified ? "Yes" : "No"} />
        <Field label="Mobile verified" value={u.is_mobile_verified ? "Yes" : "No"} />
        <Field label="Joined" value={new Date(u.created_at).toLocaleDateString()} />
      </div>

      <RequestBanBox userId={u.id} />
    </div>
  );
}

function RequestBanBox({ userId }: { userId: string }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<string>(REPORT_REASONS[0].id);
  const [detail, setDetail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  async function send() {
    const ok = await confirmAction({
      title: "Request a ban on this account?",
      message: "This sends a report to the Super Admin, who reviews it and decides whether to ban the account — you can't ban anyone directly.",
      confirmLabel: "Send request",
      danger: true,
    });
    if (!ok) return;
    setSending(true);
    try {
      await api.post("/safety/report/", { user_id: userId, reason, detail });
      toast("success", "Sent to the Super Admin for review.");
      setSent(true);
      setOpen(false);
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't send that request.");
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="u-card u-card-pad">
      <h2 className="u-h3">Something not right?</h2>
      <p className="u-fine mt-1">You can't ban an account directly — request one instead, and a Super Admin will review it.</p>

      {sent ? (
        <p className="u-alert u-alert-success mt-3">Request sent — a Super Admin will review it.</p>
      ) : !open ? (
        <button type="button" className="u-btn-secondary u-btn-sm mt-3" onClick={() => setOpen(true)}>
          Request a ban
        </button>
      ) : (
        <div className="mt-3 flex flex-col gap-3">
          <select className="u-select" value={reason} onChange={(e) => setReason(e.target.value)}>
            {REPORT_REASONS.map((r) => (
              <option key={r.id} value={r.id}>{r.label}</option>
            ))}
          </select>
          <textarea
            className="u-input"
            rows={3}
            placeholder="Any details that would help the Super Admin decide (optional)"
            value={detail}
            onChange={(e) => setDetail(e.target.value)}
          />
          <div className="flex gap-2">
            <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => setOpen(false)}>Cancel</button>
            <button type="button" className="u-btn-primary u-btn-sm" disabled={sending} onClick={send}>
              {sending ? "Sending…" : "Send request"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function Field({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div>
      <p className="text-[0.6875rem] font-semibold uppercase tracking-wide text-ink-500">{label}</p>
      <p className={`mt-0.5 text-[0.9375rem] text-ink-900 ${className ?? ""}`}>{value}</p>
    </div>
  );
}
