import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Language, Subject } from "@/lib/types";
import { confirmAction, toast } from "@/lib/ui";

type Kind = "subjects" | "languages";
type Row = Subject | Language;

interface Props {
  kind: Kind;
  /** Admin's route passes false (read-only); Super Admin's passes true.
   *  Mirrors the server: writes to /subjects/ and /languages/ are
   *  Super-Admin-only (apps/accounts/api_permissions.py). */
  canWrite: boolean;
}

const CONFIG: Record<Kind, { title: string; singular: string; endpoint: string }> = {
  subjects: { title: "Subjects", singular: "subject", endpoint: "/subjects/" },
  languages: { title: "Languages", singular: "language", endpoint: "/languages/" },
};

interface FormState {
  name: string;
  description: string; // subjects only
  icon: string; // subjects only
  code: string; // languages only
  is_active: boolean;
}

const BLANK_FORM: FormState = { name: "", description: "", icon: "", code: "", is_active: true };

/**
 * Shared list + CRUD screen for Subject and Language - the two taxonomy
 * tables whose writes were tightened to Super-Admin-only. One component
 * because the list/table/dialog plumbing is identical; only the field set
 * in the create/edit form differs (description+icon vs. code).
 */
export function TaxonomyManager({ kind, canWrite }: Props) {
  const qc = useQueryClient();
  const cfg = CONFIG[kind];
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<Row | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<FormState>(BLANK_FORM);
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: [kind, "taxonomy-manager", search],
    queryFn: () => api.list<Row>(cfg.endpoint, { params: { search: search || undefined } }),
  });
  const items = data?.items ?? [];

  function openCreate() {
    setEditing(null);
    setForm(BLANK_FORM);
    setFormError("");
    setFormOpen(true);
  }

  function openEdit(row: Row) {
    setEditing(row);
    setForm({
      name: row.name,
      description: kind === "subjects" ? (row as Subject).description ?? "" : "",
      icon: kind === "subjects" ? (row as Subject).icon ?? "" : "",
      code: kind === "languages" ? (row as Language).code : "",
      is_active: row.is_active,
    });
    setFormError("");
    setFormOpen(true);
  }

  async function save() {
    if (!form.name.trim() || submitting) return;
    setSubmitting(true);
    setFormError("");
    const payload: Record<string, unknown> =
      kind === "subjects"
        ? {
            name: form.name.trim(),
            description: form.description.trim() || null,
            icon: form.icon.trim() || null,
            is_active: form.is_active,
          }
        : { name: form.name.trim(), code: form.code.trim(), is_active: form.is_active };
    try {
      if (editing) {
        await api.patch(`${cfg.endpoint}${editing.id}/`, payload);
        toast("success", `${capitalize(cfg.singular)} updated.`);
      } else {
        await api.post(cfg.endpoint, payload);
        toast("success", `${capitalize(cfg.singular)} added.`);
      }
      setFormOpen(false);
      qc.invalidateQueries({ queryKey: [kind, "taxonomy-manager"] });
    } catch (e) {
      setFormError((e as { message?: string })?.message ?? `Couldn't save this ${cfg.singular}.`);
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleActive(row: Row) {
    try {
      await api.patch(`${cfg.endpoint}${row.id}/`, { is_active: !row.is_active });
      toast("success", row.is_active ? "Deactivated." : "Activated.");
      qc.invalidateQueries({ queryKey: [kind, "taxonomy-manager"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't update this row.");
    }
  }

  async function remove(row: Row) {
    const ok = await confirmAction({
      title: `Delete ${row.name}?`,
      message: "This can't be undone.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.del(`${cfg.endpoint}${row.id}/`);
      toast("success", "Deleted.");
      qc.invalidateQueries({ queryKey: [kind, "taxonomy-manager"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? `Couldn't delete this ${cfg.singular}.`);
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
          {canWrite && (
            <button type="button" className="u-btn-primary" onClick={openCreate}>
              Add {cfg.singular}
            </button>
          )}
        </div>
      </div>

      {!canWrite && (
        <div className="u-alert u-alert-info">
          Only a Super Admin can add, edit or delete {cfg.title.toLowerCase()}. This list is read-only for you.
        </div>
      )}

      {isError && (
        <div className="u-alert u-alert-error items-center justify-between">
          <span>{(error as { message?: string })?.message ?? `Couldn't load ${cfg.title.toLowerCase()}.`}</span>
          <button type="button" className="u-btn-secondary u-btn-sm" onClick={() => refetch()}>Try again</button>
        </div>
      )}

      {!isError && (isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
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
                {canWrite && <th className="px-4 py-2.5" />}
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
                  {canWrite && (
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-2">
                        <button type="button" className="u-btn-ghost u-btn-sm" onClick={() => toggleActive(row)}>
                          {row.is_active ? "Deactivate" : "Activate"}
                        </button>
                        <button type="button" className="u-btn-ghost u-btn-sm" onClick={() => openEdit(row)}>Edit</button>
                        <button
                          type="button"
                          className="u-btn-ghost u-btn-sm text-danger hover:bg-danger/5"
                          onClick={() => remove(row)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={canWrite ? 4 : 3} className="px-4 py-10 text-center text-ink-500">
                    No {cfg.title.toLowerCase()} match this search.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ))}

      {formOpen && (
        <div
          className="fixed inset-0 z-50 grid place-items-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label={editing ? `Edit ${cfg.singular}` : `Add ${cfg.singular}`}
        >
          <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-[2px]" onClick={() => setFormOpen(false)} />
          <div className="relative w-full max-w-sm rounded-2xl border-[1.5px] border-ink-200 bg-paper p-5 shadow-raise">
            <h2 className="u-h3">{editing ? `Edit ${cfg.singular}` : `Add ${cfg.singular}`}</h2>
            {formError && <p className="u-error mt-2">{formError}</p>}

            <div className="u-field mt-4">
              <label className="u-label" htmlFor="tm-name">Name</label>
              <input
                id="tm-name"
                className="u-input"
                autoFocus
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>

            {kind === "subjects" ? (
              <>
                <div className="u-field mt-3">
                  <label className="u-label" htmlFor="tm-description">Description</label>
                  <textarea
                    id="tm-description"
                    className="u-textarea"
                    rows={2}
                    value={form.description}
                    onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  />
                </div>
                <div className="u-field mt-3">
                  <label className="u-label" htmlFor="tm-icon">Icon key</label>
                  <input
                    id="tm-icon"
                    className="u-input"
                    value={form.icon}
                    onChange={(e) => setForm((f) => ({ ...f, icon: e.target.value }))}
                  />
                </div>
              </>
            ) : (
              <div className="u-field mt-3">
                <label className="u-label" htmlFor="tm-code">ISO code</label>
                <input
                  id="tm-code"
                  className="u-input"
                  placeholder="e.g. en, hi, bn"
                  value={form.code}
                  onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
                />
              </div>
            )}

            <label className="mt-3 flex items-center gap-2 text-[0.875rem] text-ink-600">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
              />
              Active
            </label>

            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className="u-btn-secondary" onClick={() => setFormOpen(false)}>Cancel</button>
              <button type="button" className="u-btn-primary" disabled={submitting || !form.name.trim()} onClick={save}>
                {editing ? "Save" : "Add"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function capitalize(s: string): string {
  return s ? s[0]!.toUpperCase() + s.slice(1) : s;
}
