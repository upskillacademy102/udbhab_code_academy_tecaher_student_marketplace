import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AuditLogEntry } from "@/lib/types";

const CATEGORIES = [
  { value: "", label: "All categories" },
  { value: "auth", label: "Authentication" },
  { value: "user", label: "User management" },
  { value: "security", label: "Security" },
  { value: "ops", label: "Operations" },
];

const STATUS_BADGE: Record<string, string> = {
  success: "u-badge u-badge-pine",
  failure: "u-badge u-badge-danger",
  pending: "u-badge u-badge-marigold",
};

/**
 * Mirrors superadmin/AuditLog.tsx, scoped to rows whose target is one of
 * this partner's own referred students/teachers - GET /lp/audit/ (see
 * apps.learning_partner.views.LPAuditView).
 */
export function AuditLog() {
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["lp-audit", category, page],
    queryFn: () =>
      api.list<AuditLogEntry>("/lp/audit/", {
        params: { category: category || undefined, page },
      }),
  });
  const items = data?.items ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="u-h2">Audit log</h1>
        <select
          className="u-select"
          value={category}
          onChange={(e) => {
            setPage(1);
            setCategory(e.target.value);
          }}
        >
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
      </div>

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? "Couldn't load the audit log."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {!isError && (isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-xl bg-ink-100" />
          ))}
        </div>
      ) : (
        <div className="u-card overflow-hidden">
          <table className="w-full text-left text-[0.8125rem]">
            <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
              <tr>
                <th className="px-4 py-2.5">When</th>
                <th className="px-4 py-2.5">Actor</th>
                <th className="px-4 py-2.5">Category</th>
                <th className="px-4 py-2.5">Action</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {items.map((row) => (
                <tr key={row.id}>
                  <td className="px-4 py-3 whitespace-nowrap text-ink-500">
                    {new Date(row.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <p className="font-medium text-ink-900">{row.actor_name || "system"}</p>
                    {row.actor_role && <p className="text-ink-500 capitalize">{row.actor_role}</p>}
                  </td>
                  <td className="px-4 py-3"><span className="u-badge u-badge-ink capitalize">{row.category.replace(/_/g, " ")}</span></td>
                  <td className="px-4 py-3 font-mono text-[0.75rem] text-ink-700">{row.action}</td>
                  <td className="px-4 py-3">
                    <span className={STATUS_BADGE[row.status] ?? "u-badge u-badge-ink"}>{row.status}</span>
                  </td>
                  <td className="px-4 py-3 text-ink-600">
                    {row.message}
                    {row.target_repr && <span className="text-ink-400"> · {row.target_repr}</span>}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-ink-500">No events match this filter.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ))}

      <div className="flex items-center justify-between">
        <span className="text-[0.8125rem] text-ink-500">
          {data?.meta.count != null ? `${data.meta.count} total` : ""}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            className="u-btn-secondary u-btn-sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </button>
          <button
            type="button"
            className="u-btn-secondary u-btn-sm"
            disabled={!data?.meta.next}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
