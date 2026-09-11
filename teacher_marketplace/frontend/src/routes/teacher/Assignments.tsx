import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Assignment } from "@/lib/types";
import { toast } from "@/lib/ui";

/**
 * Time-limited offers of a lead.
 *
 * These expire, so the countdown is the most important thing on each card,
 * not a footnote. Anything under two hours is shown in marigold — the only
 * place on this page that colour appears, so it reads as urgency rather than
 * decoration.
 *
 * The four match scores are shown as a single "why you" line rather than
 * four bars: a teacher deciding in ten seconds needs the reason, not the
 * breakdown.
 */

function timeLeft(expiresAt?: string | null): { text: string; urgent: boolean; gone: boolean } {
  if (!expiresAt) return { text: "", urgent: false, gone: false };
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return { text: "expired", urgent: false, gone: true };
  const mins = Math.round(ms / 60000);
  if (mins < 60) return { text: `${mins} min left`, urgent: true, gone: false };
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return { text: `${hrs}h left`, urgent: hrs <= 2, gone: false };
  const days = Math.round(hrs / 24);
  return { text: `${days}d left`, urgent: false, gone: false };
}

function whyYou(a: Assignment): string {
  const bits: string[] = [];
  if ((a.subject_match_score ?? 0) > 0) bits.push("your subject");
  if ((a.time_match_score ?? 0) > 0) bits.push("your hours");
  if ((a.language_match_score ?? 0) > 0) bits.push("your language");
  if ((a.location_score ?? 0) > 0) bits.push("your area");
  if (!bits.length) return "Matched to your profile";
  if (bits.length === 1) return `Matches ${bits[0]}`;
  return `Matches ${bits.slice(0, -1).join(", ")} and ${bits[bits.length - 1]}`;
}

export function Assignments() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["assignments"],
    queryFn: () => api.list<Assignment>("/matching/assignments/"),
  });

  const items = (data?.items ?? []).filter((a) => (a.status ?? "").toLowerCase() === "pending" || !a.response);

  async function respond(a: Assignment, action: "accept" | "reject") {
    setBusy(a.id);
    try {
      await api.post(`/matching/assignments/${a.id}/${action}/`, {});
      toast("success", action === "accept" ? "Added to your enquiries." : "Passed on it.");
      qc.invalidateQueries({ queryKey: ["assignments"] });
      qc.invalidateQueries({ queryKey: ["leads"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't do that.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <h1 className="u-h2">
        {isLoading ? "Loading…" : items.length ? `${items.length} offer${items.length === 1 ? "" : "s"} for you` : "Offers"}
      </h1>

      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => <div key={i} className="h-44 animate-pulse rounded-2xl bg-ink-100" />)}
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
            When a student matches you closely, you get first refusal here before the enquiry goes wider.
            Accepting adds it to your enquiries — it doesn't spend an unlock.
          </p>
        </section>
      )}

      {items.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          {items.map((a, i) => {
            const t = timeLeft(a.expires_at);
            return (
              <article
                key={a.id}
                className="u-stagger-item flex flex-col gap-3 rounded-2xl border-[1.5px] border-ink-300 bg-paper p-5 shadow-lift"
                style={{ "--d": `${Math.min(i, 7) * 30}ms` } as React.CSSProperties}
              >
                <div className="flex items-start justify-between gap-3">
                  <h2 className="min-w-0 truncate text-[1rem] font-semibold text-ink-900">
                    {a.subject_name ?? "Enquiry"}
                  </h2>
                  {t.text && (
                    <span
                      className={
                        "shrink-0 rounded-full px-2.5 py-1 text-[0.6875rem] font-bold uppercase tracking-wide " +
                        (t.gone
                          ? "bg-ink-100 text-ink-500"
                          : t.urgent
                            ? "bg-marigold-500 text-ink-900"
                            : "bg-pine-100 text-pine-800")
                      }
                    >
                      {t.text}
                    </span>
                  )}
                </div>

                <p className="u-fine">{whyYou(a)}</p>

                <div className="mt-auto flex gap-2 border-t border-ink-200 pt-3">
                  <button
                    type="button"
                    className="u-btn-primary u-btn-sm flex-1"
                    disabled={busy === a.id || t.gone}
                    data-loading={busy === a.id || undefined}
                    onClick={() => respond(a, "accept")}
                  >
                    Take it
                  </button>
                  <button
                    type="button"
                    className="u-btn-secondary u-btn-sm"
                    disabled={busy === a.id || t.gone}
                    onClick={() => respond(a, "reject")}
                  >
                    Pass
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
