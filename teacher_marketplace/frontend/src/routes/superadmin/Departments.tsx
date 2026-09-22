import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AdminDepartment } from "@/lib/types";
import { confirmAction, toast } from "@/lib/ui";

/**
 * Departments an approved admin can be assigned to — a fixed-but-editable
 * list (seeded once, Super Admin can add more here). Deleting one that
 * still has active admins is refused server-side; the button here just
 * mirrors that rather than trying to guess it client-side.
 */
export function Departments() {
  const qc = useQueryClient();
  // null = closed, "new" = create dialog, an AdminDepartment = rename dialog.
  const [editing, setEditing] = useState<AdminDepartment | "new" | null>(null);
  const [name, setName] = useState("");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["staff-departments"],
    queryFn: () => api.list<AdminDepartment>("/auth/staff/departments/"),
  });

  const items = data?.items ?? [];

  function openCreate() {
    setEditing("new");
    setName("");
    setFormError("");
  }

  function openRename(d: AdminDepartment) {
    setEditing(d);
    setName(d.name);
    setFormError("");
  }

  async function save() {
    if (!name.trim() || submitting || editing === null) return;
    setSubmitting(true);
    setFormError("");
    try {
      if (editing === "new") {
        await api.post("/auth/staff/departments/", { name: name.trim() });
        toast("success", "Department created.");
      } else {
        await api.patch(`/auth/staff/departments/${editing.id}/`, { name: name.trim() });
        toast("success", "Department renamed.");
      }
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["staff-departments"] });
    } catch (e) {
      setFormError(
        (e as { message?: string })?.message ??
          `Couldn't ${editing === "new" ? "create" : "rename"} this department.`,
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleActive(d: AdminDepartment) {
    try {
      await api.patch(`/auth/staff/departments/${d.id}/`, { is_active: !d.is_active });
      toast("success", d.is_active ? "Department deactivated." : "Department activated.");
      qc.invalidateQueries({ queryKey: ["staff-departments"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't update this department.");
    }
  }

  async function remove(d: AdminDepartment) {
    const ok = await confirmAction({
      title: `Delete ${d.name}?`,
      message: "This can't be undone. Departments with active admins can't be deleted.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.del(`/auth/staff/departments/${d.id}/`);
      toast("success", "Department deleted.");
      qc.invalidateQueries({ queryKey: ["staff-departments"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't delete this department.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="u-h2">
          {isLoading ? "Loading…" : isError ? "Departments" : `${items.length} department${items.length === 1 ? "" : "s"}`}
        </h1>
        <button type="button" className="u-btn-primary" onClick={openCreate}>
          Add department
        </button>
      </div>

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? "Couldn't load departments."}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {!isError && (isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-xl bg-ink-100" />
          ))}
        </div>
      ) : (
        <div className="u-card overflow-hidden">
          <table className="w-full text-left text-[0.875rem]">
            <thead className="bg-paper-sunk text-[0.6875rem] font-semibold uppercase tracking-wider text-ink-500">
              <tr>
                <th className="px-4 py-2.5">Name</th>
                <th className="px-4 py-2.5">Admins</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {items.map((d) => (
                <tr key={d.id}>
                  <td className="px-4 py-3 font-medium text-ink-900">
                    {d.name}
                    {d.is_learning_partner && <span className="u-badge u-badge-ink ml-2">Learning Partner</span>}
                  </td>
                  <td className="px-4 py-3 text-ink-600">{d.admin_count}</td>
                  <td className="px-4 py-3">
                    <span className={d.is_active ? "u-badge u-badge-pine" : "u-badge u-badge-ink"}>
                      {d.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-2">
                      <button
                        type="button"
                        className="u-btn-ghost u-btn-sm"
                        disabled={d.is_learning_partner}
                        title={d.is_learning_partner ? "Required by the platform — can't be renamed" : undefined}
                        onClick={() => openRename(d)}
                      >
                        Rename
                      </button>
                      <button type="button" className="u-btn-ghost u-btn-sm" onClick={() => toggleActive(d)}>
                        {d.is_active ? "Deactivate" : "Activate"}
                      </button>
                      <button
                        type="button"
                        className="u-btn-ghost u-btn-sm text-danger hover:bg-danger/5"
                        disabled={d.admin_count > 0 || d.is_learning_partner}
                        title={
                          d.is_learning_partner
                            ? "Required by the platform — can't be removed"
                            : d.admin_count > 0
                              ? "Has active admins assigned"
                              : undefined
                        }
                        onClick={() => remove(d)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-ink-500">No departments yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ))}

      {editing !== null && (
        <div
          className="fixed inset-0 z-50 grid place-items-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label={editing === "new" ? "Add department" : "Rename department"}
        >
          <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-[2px]" onClick={() => setEditing(null)} />
          <div className="relative w-full max-w-sm rounded-2xl border-[1.5px] border-ink-200 bg-paper p-5 shadow-raise">
            <h2 className="u-h3">{editing === "new" ? "Add department" : `Rename ${editing.name}`}</h2>
            {formError && <p className="u-error mt-2">{formError}</p>}
            <div className="u-field mt-4">
              <label className="u-label" htmlFor="dept-name">Name</label>
              <input
                id="dept-name"
                className="u-input"
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && save()}
                placeholder="e.g. Compliance"
              />
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className="u-btn-secondary" onClick={() => setEditing(null)}>Cancel</button>
              <button type="button" className="u-btn-primary" disabled={submitting || !name.trim()} onClick={save}>
                {editing === "new" ? "Create" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
