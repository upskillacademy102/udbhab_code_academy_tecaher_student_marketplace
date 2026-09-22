import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Language, LearningPartnerTaxonomyRequest, Subject } from "@/lib/types";
import { toast } from "@/lib/ui";

type Kind = "subjects" | "languages";
type Row = Subject | Language;

interface Props {
  kind: Kind;
}

const CONFIG: Record<
  Kind,
  { title: string; singular: string; endpoint: string; requestKind: "subject" | "language" }
> = {
  subjects: { title: "Subjects", singular: "subject", endpoint: "/subjects/", requestKind: "subject" },
  languages: { title: "Languages", singular: "language", endpoint: "/languages/", requestKind: "language" },
};

const STATUS_BADGE: Record<LearningPartnerTaxonomyRequest["status"], string> = {
  pending: "u-badge u-badge-marigold",
  approved: "u-badge u-badge-pine",
  denied: "u-badge u-badge-ink",
};

/**
 * A Learning Partner's own Subjects/Languages screen - read-only (writes to
 * /subjects/ and /languages/ stay Super-Admin-only, apps/accounts/
 * api_permissions.py) plus a "Request new" flow: submitting opens a
 * LearningPartnerTaxonomyRequest a Super Admin reviews, which becomes a
 * real subject/language scoped to this partner alone once approved.
 * Mirrors TaxonomyManager.tsx's list shape with canWrite=false, and adds
 * the requests list underneath.
 */
export function LPTaxonomyManager({ kind }: Props) {
  const qc = useQueryClient();
  const cfg = CONFIG[kind];
  const [search, setSearch] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: [kind, "lp-taxonomy", search],
    queryFn: () => api.list<Row>(cfg.endpoint, { params: { search: search || undefined } }),
  });
  const items = data?.items ?? [];

  const { data: requestsData, isLoading: requestsLoading } = useQuery({
    queryKey: ["lp-taxonomy-requests", cfg.requestKind],
    queryFn: () =>
      api.get<LearningPartnerTaxonomyRequest[]>("/lp/taxonomy-requests/", {
        params: { kind: cfg.requestKind },
      }),
  });
  const requests = requestsData ?? [];

  function openRequestForm() {
    setName("");
    setNote("");
    setFormError("");
    setFormOpen(true);
  }

  async function submitRequest() {
    if (!name.trim() || submitting) return;
    setSubmitting(true);
    setFormError("");
    try {
      await api.post("/lp/taxonomy-requests/", {
        kind: cfg.requestKind,
        name: name.trim(),
        note: note.trim(),
      });
      toast("success", "Sent to the Super Admin for review.");
      setFormOpen(false);
      qc.invalidateQueries({ queryKey: ["lp-taxonomy-requests", cfg.requestKind] });
    } catch (e) {
      setFormError((e as { message?: string })?.message ?? `Couldn't send this request.`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="u-h2">
          {isLoading ? "Loading…" : isError ? cfg.title : `${items.length} ${cfg.title.toLowerCase()}`}
        </h1>
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="u-input w-56"
            placeholder={`Search ${cfg.title.toLowerCase()}`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button type="button" className="u-btn-primary" onClick={openRequestForm}>
            Request new {cfg.singular}
          </button>
        </div>
      </div>

      <div className="u-alert u-alert-info">
        This list is read-only — only a Super Admin can add, edit or retire {cfg.title.toLowerCase()}.
        Don't see one your students/teachers need? Request it below.
      </div>

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? `Couldn't load ${cfg.title.toLowerCase()}.`}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {!isError && (isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-xl bg-ink-100" />
          ))}
        </div>
      ) : (
        <div className="u-card overflow-hidden">
          <table className="w-full text-left text-[0.875rem]">
            <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
              <tr>
                <th className="px-4 py-2.5">Name</th>
                <th className="px-4 py-2.5">{kind === "subjects" ? "Description" : "Code"}</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Scope</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {items.map((row) => (
                <tr key={row.id}>
                  <td className="px-4 py-3 font-medium text-ink-900">{row.name}</td>
                  <td className="px-4 py-3 text-ink-600">
                    {kind === "subjects" ? (row as Subject).description || "—" : (row as Language).code || "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span className={row.is_active ? "u-badge u-badge-pine" : "u-badge u-badge-ink"}>
                      {row.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {row.learning_partner ? (
                      <span className="u-badge u-badge-marigold">Your organisation</span>
                    ) : (
                      <span className="text-ink-500">Platform-wide</span>
                    )}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-ink-500">
                    No {cfg.title.toLowerCase()} match this search.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ))}

      <div className="flex flex-col gap-3">
        <h2 className="u-h3">Your requests</h2>
        {requestsLoading && (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 2 }).map((_, i) => (
              <div key={i} className="h-14 animate-pulse rounded-xl bg-ink-100" />
            ))}
          </div>
        )}
        {!requestsLoading && requests.length === 0 && (
          <div className="u-card u-card-pad text-center text-ink-500">
            No {cfg.singular} requests yet.
          </div>
        )}
        {!requestsLoading && requests.length > 0 && (
          <div className="flex flex-col gap-2">
            {requests.map((r) => (
              <div key={r.id} className="u-card u-card-pad flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-ink-900">{r.name}</span>
                    <span className={STATUS_BADGE[r.status]}>{r.status[0]!.toUpperCase() + r.status.slice(1)}</span>
                  </div>
                  {r.note && <p className="u-fine mt-1">{r.note}</p>}
                  {r.status === "denied" && r.deny_reason && (
                    <p className="mt-1 text-[0.8125rem] text-ink-500">Reason: {r.deny_reason}</p>
                  )}
                </div>
                <p className="u-fine">{new Date(r.created_at).toLocaleString("en-IN")}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {formOpen && (
        <div
          className="fixed inset-0 z-50 grid place-items-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label={`Request a new ${cfg.singular}`}
        >
          <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-[2px]" onClick={() => setFormOpen(false)} />
          <div className="relative w-full max-w-sm rounded-2xl border-[1.5px] border-ink-200 bg-paper p-5 shadow-raise">
            <h2 className="u-h3">Request a new {cfg.singular}</h2>
            <p className="u-fine mt-2">
              A Super Admin reviews this. If approved, it's visible only to your own students/teachers.
            </p>
            {formError && <p className="u-error mt-3">{formError}</p>}

            <div className="u-field mt-4">
              <label className="u-label" htmlFor="lp-tax-name">Name</label>
              <input
                id="lp-tax-name"
                className="u-input"
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="u-field mt-3">
              <label className="u-label" htmlFor="lp-tax-note">Note (optional)</label>
              <textarea
                id="lp-tax-note"
                className="u-textarea"
                rows={2}
                placeholder="Why your students/teachers need this."
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className="u-btn-secondary" onClick={() => setFormOpen(false)}>Cancel</button>
              <button type="button" className="u-btn-primary" disabled={submitting || !name.trim()} onClick={submitRequest}>
                Send request
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
