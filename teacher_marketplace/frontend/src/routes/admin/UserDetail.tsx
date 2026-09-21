import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AdminUser } from "@/lib/types";

/** Read-only — Admin's `admin_users:detail` grant is GET only. */
export function UserDetail() {
  const { id } = useParams<{ id: string }>();
  const user = useQuery({
    queryKey: ["admin-user", id],
    queryFn: () => api.get<AdminUser>(`/admin/users/${id}/`),
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
        <span>{(user.error as { message?: string })?.message ?? "Couldn't load this user."}</span>
        <Link to="/staff/admin/users/" className="u-btn-secondary u-btn-sm">Back to Users</Link>
      </div>
    );
  }

  const u = user.data;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link to="/staff/admin/users/" className="text-[0.8125rem] text-ink-500 hover:underline">← All users</Link>
        <h1 className="u-h2 mt-1">{u.full_name || "(no name)"}</h1>
      </div>

      <div className="u-card grid grid-cols-1 gap-4 p-4 sm:grid-cols-2">
        <Field label="Email" value={u.email} />
        <Field label="Mobile" value={u.mobile} />
        <Field label="Role" value={u.role} className="capitalize" />
        <Field label="Status" value={u.is_active ? "Active" : "Inactive"} />
        <Field label="Email verified" value={u.is_email_verified ? "Yes" : "No"} />
        <Field label="Mobile verified" value={u.is_mobile_verified ? "Yes" : "No"} />
        <Field label="Joined" value={new Date(u.created_at).toLocaleDateString()} />
      </div>
    </div>
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
