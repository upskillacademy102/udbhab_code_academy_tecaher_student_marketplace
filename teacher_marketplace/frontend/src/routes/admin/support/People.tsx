import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { SupportContactUser } from "@/lib/types";

const TITLES: Record<"student" | "teacher" | "learning_partner", string> = {
  student: "Students",
  teacher: "Teachers",
  learning_partner: "Learning Partners",
};

/**
 * Support-department admin's view of Students / Teachers / Learning
 * Partners - name, email, and phone only. Backed by the same admin_users:*
 * endpoint every admin uses, but the API swaps in
 * SupportContactUserSerializer for a Support-department caller, so this
 * page can never receive more than contact info even if it asked for it.
 */
export function People({ role }: { role: "student" | "teacher" | "learning_partner" }) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const users = useQuery({
    queryKey: ["support-people", role, search, page],
    queryFn: () =>
      api.list<SupportContactUser>("/admin/users/", {
        params: { role, search: search || undefined, page },
      }),
  });
  const items = users.data?.items ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="u-h2">{TITLES[role]}</h1>
        <input
          className="u-input w-64"
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
          <span>{(users.error as { message?: string })?.message ?? "Couldn't load this list."}</span>
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
                <th className="px-4 py-2.5">Email</th>
                <th className="px-4 py-2.5">Phone</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {items.map((u) => (
                <tr key={u.id}>
                  <td className="px-4 py-3 font-medium text-ink-900">{u.full_name || "(no name)"}</td>
                  <td className="px-4 py-3 text-ink-600">{u.email}</td>
                  <td className="px-4 py-3 text-ink-600">{u.mobile || "—"}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-4 py-10 text-center text-ink-500">No matches.</td>
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
