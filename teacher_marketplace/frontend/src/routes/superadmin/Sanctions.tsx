import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AccountSanction } from "@/lib/types";
import { confirmAction, sanctionLabel, toast } from "@/lib/ui";

const STATUS_TABS = [
  { value: "true", label: "Active" },
  { value: "false", label: "Lifted" },
  { value: "", label: "All" },
] as const;

const SOURCE_OPTIONS = [
  { value: "", label: "All sources" },
  { value: "manual", label: "Manual (Super Admin)" },
  { value: "auto_", label: "Automatic (any)" },
  { value: "auto_fake_leads_weekly", label: "Auto — fake leads (weekly)" },
  { value: "auto_fake_leads_monthly", label: "Auto — fake leads (monthly)" },
  { value: "auto_staff_login_bruteforce", label: "Auto — staff login brute force" },
];

/** Full ban/suspend history across the platform — the audit trail behind
 *  every Ban/Unban button on the Users screens, plus every automatic ban. */
export function Sanctions() {
  const qc = useQueryClient();
  const [active, setActive] = useState<(typeof STATUS_TABS)[number]["value"]>("true");
  const [source, setSource] = useState("");
  const [page, setPage] = useState(1);

  const params: Record<string, string | number> = { page };
  if (active) params.active = active;
  if (source === "auto_") params.source_prefix = "auto_";
  else if (source) params.source = source;

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["ops-sanctions", "browse", active, source, page],
    queryFn: () => api.list<AccountSanction>("/ops/sanctions/", { params }),
  });

  async function lift(s: AccountSanction) {
    const ok = await confirmAction({ title: `Unban ${s.user_email}?`, confirmLabel: "Unban" });
    if (!ok) return;
    try {
      await api.post(`/ops/sanctions/${s.id}/lift/`, {});
      toast("success", `${s.user_email} has been reactivated.`);
      qc.invalidateQueries({ queryKey: ["ops-sanctions"] });
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't unban this account.");
    }
  }

  const items = data?.items ?? [];

  return (
    <div className="flex flex-col gap-6">
      <h1 className="u-h2">Bans &amp; sanctions</h1>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1.5">
          {STATUS_TABS.map((t) => (
            <button
              key={t.value}
              type="button"
              className="u-chip u-chip-sm"
              aria-pressed={active === t.value}
              onClick={() => {
                setPage(1);
                setActive(t.value);
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
        <select
          className="u-select"
          value={source}
          onChange={(e) => {
            setPage(1);
            setSource(e.target.value);
          }}
        >
          {SOURCE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? "Couldn't load sanctions."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {!isError && (isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-xl bg-ink-100" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="u-card p-6 text-center text-ink-500">No sanctions match this filter.</div>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((s) => (
            <li key={s.id} className="u-card flex flex-wrap items-center justify-between gap-3 p-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={`/staff/superadmin/users/${s.user}/`} className="font-medium text-ink-900 hover:underline">
                    {s.user_email}
                  </Link>
                  <span className="u-badge u-badge-ink capitalize">{s.user_role}</span>
                  <span className={s.active ? "u-badge u-badge-danger" : "u-badge u-badge-ink"}>
                    {sanctionLabel(s.kind)}{s.active ? "" : " (lifted)"}
                  </span>
                  {s.is_automatic && <span className="u-badge u-badge-marigold">Automatic</span>}
                </div>
                <p className="mt-1 text-[0.8125rem] text-ink-600">{s.reason || "No reason given."}</p>
                <p className="text-[0.75rem] text-ink-400">
                  {new Date(s.created_at).toLocaleString()}
                  {!s.is_automatic && s.created_by_email ? ` · by ${s.created_by_email}` : ""}
                </p>
              </div>
              {s.active && s.user_role !== "superadmin" && (
                <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => lift(s)}>Unban</button>
              )}
            </li>
          ))}
        </ul>
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
