import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AdminUser } from "@/lib/types";

/**
 * Shared list shell for the Learning Partner's Students/Teachers screens —
 * same shape as the admin Users list, but the endpoint already scopes to
 * "my own referred people" server-side (apps.learning_partner.views), so
 * there is no role filter to offer here — every row IS the right role.
 */
export function LPUserList({
  endpoint, basePath, noun,
}: {
  endpoint: string;
  basePath: string;
  noun: string;
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const users = useQuery({
    queryKey: [endpoint, search, page],
    queryFn: () =>
      api.list<AdminUser>(endpoint, { params: { search: search || undefined, page } }),
  });
  const items = users.data?.items ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="u-h2">{noun}</h1>
        <input
          className="u-input w-56"
          placeholder="Search name, email, mobile"
          value={search}
          onChange={(e) => {
            setPage(1);
            setSearch(e.target.value);
          }}
        />
      </div>

      {users.isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(users.error as { message?: string })?.message ?? `Couldn't load ${noun.toLowerCase()}.`}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => users.refetch()}>Try again</button>
        </div>
      )}

      {!users.isError && (users.isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-xl bg-ink-100" />
          ))}
        </div>
      ) : (
        <div className="u-card overflow-hidden">
          <table className="w-full text-left text-[0.875rem]">
            <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
              <tr>
                <th className="px-4 py-2.5">Name</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {items.map((u) => (
                <tr key={u.id}>
                  <td className="px-4 py-3">
                    <Link to={`${basePath}${u.id}/`} className="font-medium text-ink-900 hover:underline">
                      {u.full_name || "(no name)"}
                    </Link>
                    <p className="text-ink-500">{u.email}</p>
                  </td>
                  <td className="px-4 py-3">
                    <span className={u.is_active ? "u-badge u-badge-pine" : "u-badge u-badge-ink"}>
                      {u.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link to={`${basePath}${u.id}/`} className="u-btn-ghost u-btn-sm">View</Link>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-4 py-10 text-center text-ink-500">
                    No {noun.toLowerCase()} have identified your organisation yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ))}

      <div className="flex items-center justify-between">
        <span className="text-[0.8125rem] text-ink-500">
          {users.data?.meta.count != null ? `${users.data.meta.count} total` : ""}
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
            disabled={!users.data?.meta.next}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
