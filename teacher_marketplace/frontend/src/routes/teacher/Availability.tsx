import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { DAYS } from "@/lib/intent";
import { confirmAction, toast } from "@/lib/ui";

/**
 * When this teacher can actually teach.
 *
 * The highest-leverage screen in the teacher area: the matching engine scores
 * real time overlap between these windows and a student's free hours, so an
 * empty week means never being matched at all. The copy leads with that
 * rather than treating it as settings.
 *
 * Windows are grouped by day so the week reads as a week. One-off closures
 * live underneath, clearly separate from the recurring pattern.
 */

const TZ = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
  } catch {
    return "Asia/Kolkata";
  }
})();

interface Weekly {
  id: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
  timezone: string;
  is_active?: boolean;
}

interface Exception {
  id: string;
  date: string;
  reason?: string | null;
  exception_type?: string | null;
}

const PRESETS = [
  { label: "Morning", start: "09:00", end: "12:00" },
  { label: "Evening", start: "18:00", end: "21:00" },
  { label: "Full Day", start: "06:00", end: "22:00" },
] as const;

export function Availability() {
  const qc = useQueryClient();
  const [day, setDay] = useState(1);
  const [start, setStart] = useState("18:00");
  const [end, setEnd] = useState("20:00");
  const [adding, setAdding] = useState(false);
  const [applyingAll, setApplyingAll] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const weekly = useQuery({
    queryKey: ["weekly-availability"],
    queryFn: () => api.list<Weekly>("/teachers/profile/weekly-availability/"),
  });
  const exceptions = useQuery({
    queryKey: ["schedule-exceptions"],
    queryFn: () => api.list<Exception>("/teachers/profile/schedule-exceptions/"),
  });

  const windows = weekly.data?.items ?? [];
  const closures = exceptions.data?.items ?? [];

  async function addWindow() {
    if (start >= end) return toast("warning", "The end time has to be after the start time.");
    setAdding(true);
    try {
      await api.post("/teachers/profile/weekly-availability/", {
        day_of_week: Number(day), start_time: start, end_time: end, timezone: TZ,
      }, { silent: true });
      toast("success", "Added.");
      qc.invalidateQueries({ queryKey: ["weekly-availability"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't add that.");
    } finally {
      setAdding(false);
    }
  }

  // Copies the currently-set From/To window onto every day of the week in
  // one go, rather than clicking through all seven. Per-day POSTs run
  // independently (allSettled) so one day already having an overlapping
  // window doesn't block the rest from being created.
  async function applyToAllDays() {
    if (start >= end) return toast("warning", "The end time has to be after the start time.");
    setApplyingAll(true);
    try {
      const results = await Promise.allSettled(
        DAYS.map((d) =>
          api.post("/teachers/profile/weekly-availability/", {
            day_of_week: d.n, start_time: start, end_time: end, timezone: TZ,
          }, { silent: true }),
        ),
      );
      const okCount = results.filter((r) => r.status === "fulfilled").length;
      if (okCount > 0) {
        toast("success", `Applied ${start}–${end} to ${okCount} of ${DAYS.length} days.`);
      } else {
        toast("error", "Couldn't apply that to any day — it may already overlap something.");
      }
      qc.invalidateQueries({ queryKey: ["weekly-availability"] });
    } finally {
      setApplyingAll(false);
    }
  }

  // Everything on this page already saves the moment you add or remove it —
  // there's no separate draft state. This just forces a fresh pull from the
  // server so what's on screen is confirmed, not merely assumed, current.
  async function saveChanges() {
    setSyncing(true);
    try {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["weekly-availability"] }),
        qc.invalidateQueries({ queryKey: ["schedule-exceptions"] }),
      ]);
      toast("success", "Your schedule is saved and up to date.");
    } finally {
      setSyncing(false);
    }
  }

  async function removeWindow(w: Weekly) {
    try {
      await api.del(`/teachers/profile/weekly-availability/${w.id}/`);
      qc.invalidateQueries({ queryKey: ["weekly-availability"] });
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't remove that.");
    }
  }

  function addSlotForDay(dayNumber: number) {
    setDay(dayNumber);
    document.getElementById("av-from")?.focus();
    document.getElementById("av-day-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const byDay = DAYS.map((d) => ({
    ...d,
    windows: windows
      .filter((w) => w.day_of_week === d.n)
      .sort((a, b) => a.start_time.localeCompare(b.start_time)),
  }));
  const total = windows.length;

  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="u-h2">Availability &amp; Scheduling</h1>
          <p className="u-fine mt-1">Define your regular recurring booking windows and block out vacations or personal days.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="u-btn-secondary u-btn-sm inline-flex items-center gap-1.5"
            onClick={applyToAllDays} data-loading={applyingAll || undefined} disabled={applyingAll}>
            <CopyIcon /> Apply to all days
          </button>
          <button type="button" className="u-btn-primary u-btn-sm inline-flex items-center gap-1.5"
            onClick={saveChanges} data-loading={syncing || undefined} disabled={syncing}>
            <CheckIcon /> Save changes
          </button>
        </div>
      </div>

      {!weekly.isLoading && total === 0 && (
        <section className="u-card u-card-pad border-marigold-400 bg-marigold-50">
          <h2 className="u-h3">No hours set, so no students</h2>
          <p className="u-body mt-1.5 text-ink-700">
            We match students to teachers who are genuinely free when they are. With an empty week, you won't
            appear in anyone's results. Add one window below to start.
          </p>
        </section>
      )}

      <section id="av-day-card" className="u-card u-card-pad">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md bg-pine-100 text-pine-700">
              <PlusIcon />
            </span>
            <div>
              <h2 className="u-h3">Add a time you're free</h2>
              <p className="u-fine mt-0.5">Set specific recurring windows. Times will be saved in your active timezone ({TZ}).</p>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-1.5">
            <span className="u-fine">Presets:</span>
            {PRESETS.map((p) => (
              <button key={p.label} type="button" className="u-chip u-chip-sm"
                onClick={() => { setStart(p.start); setEnd(p.end); }}>
                {p.label}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div className="u-field min-w-[10rem] flex-1">
            <label className="u-label" htmlFor="av-day">Select Day</label>
            <select id="av-day" className="u-select" value={day} onChange={(e) => setDay(Number(e.target.value))}>
              {DAYS.map((d) => <option key={d.n} value={d.n}>{d.full}</option>)}
            </select>
          </div>
          <div className="u-field">
            <label className="u-label" htmlFor="av-from">From</label>
            <input id="av-from" type="time" step={900} className="u-input" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="u-field">
            <label className="u-label" htmlFor="av-to">To</label>
            <input id="av-to" type="time" step={900} className="u-input" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <button type="button" className="u-btn-primary inline-flex items-center gap-1.5" onClick={addWindow} data-loading={adding || undefined} disabled={adding}>
            <PlusIcon /> Add
          </button>
        </div>
      </section>

      <section className="u-card overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-ink-200 px-5 py-4">
          <div className="flex items-center gap-2">
            <h2 className="u-h3">Your week</h2>
            {total > 0 && <span className="u-badge u-badge-pine">Active Schedule</span>}
          </div>
          <span className="u-fine">{total} {total === 1 ? "window" : "windows"} configured</span>
        </div>

        {weekly.isLoading ? (
          <div className="flex flex-col gap-2 p-4">
            {Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-ink-100" />)}
          </div>
        ) : (
          <ul className="divide-y divide-ink-200">
            {byDay.map((d) => (
              <li key={d.n} className="flex items-start justify-between gap-4 px-5 py-3.5">
                <div className="flex items-start gap-4">
                  <span className={"w-24 shrink-0 text-[0.875rem] font-semibold " + (d.windows.length ? "text-ink-900" : "text-ink-400")}>
                    {d.full}
                  </span>
                  {d.windows.length === 0 ? (
                    <span className="u-fine">—</span>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {d.windows.map((w) => (
                        <span key={w.id}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-pine-300 bg-pine-50 py-1 pl-2.5 pr-2 text-[0.8125rem] font-semibold tabular-nums text-pine-800">
                          <ClockIcon />
                          {w.start_time.slice(0, 5)} – {w.end_time.slice(0, 5)}
                          <button type="button" onClick={() => removeWindow(w)}
                            className="grid h-4 w-4 place-items-center rounded-full bg-pine-600 text-[10px] leading-none text-white transition hover:bg-pine-800"
                            aria-label={`Remove ${d.full} ${w.start_time.slice(0, 5)} to ${w.end_time.slice(0, 5)}`}>
                            ×
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <button type="button" className="u-link shrink-0 whitespace-nowrap text-[0.8125rem]" onClick={() => addSlotForDay(d.n)}>
                  + Add slot
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Closures items={closures} loading={exceptions.isLoading}
        onChanged={() => qc.invalidateQueries({ queryKey: ["schedule-exceptions"] })} />
    </div>
  );
}

function Closures({ items, loading, onChanged }: { items: Exception[]; loading: boolean; onChanged: () => void }) {
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function add() {
    if (!date) return toast("warning", "Pick a date.");
    setBusy(true);
    try {
      await api.post("/teachers/profile/schedule-exceptions/", {
        date, reason: reason || null, exception_type: "unavailable",
      }, { silent: true });
      toast("success", "Added.");
      setDate("");
      setReason("");
      onChanged();
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't add that.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(x: Exception) {
    const ok = await confirmAction({ title: "Remove this day off?", confirmLabel: "Remove", danger: true });
    if (!ok) return;
    try {
      await api.del(`/teachers/profile/schedule-exceptions/${x.id}/`);
      onChanged();
    } catch (e) {
      toast("error", (e as { message?: string })?.message ?? "Couldn't remove that.");
    }
  }

  return (
    <section className="u-card u-card-pad">
      <h2 className="u-h3">Days off</h2>
      <p className="u-fine mt-0.5">One-off dates you're away. Your weekly pattern stays as it is.</p>

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <div className="u-field">
          <label className="u-label" htmlFor="ex-date">Date</label>
          <input id="ex-date" type="date" className="u-input" value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
        <div className="u-field min-w-[12rem] flex-1">
          <label className="u-label" htmlFor="ex-why">Why (optional)</label>
          <input id="ex-why" className="u-input" placeholder="e.g. Travelling, National Holiday, Tournament" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <button type="button" className="u-btn-secondary" onClick={add} data-loading={busy || undefined} disabled={busy}>
          Add
        </button>
      </div>

      {!loading && items.length > 0 && (
        <div className="mt-4 border-t border-ink-200 pt-4">
          <p className="u-eyebrow">Upcoming scheduled days off</p>
          <ul className="mt-2.5 flex flex-wrap gap-2">
            {items.map((x) => (
              <li key={x.id}
                className="inline-flex items-center gap-2 rounded-full border border-marigold-300 bg-marigold-50 py-1.5 pl-3 pr-2 text-[0.8125rem]">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-marigold-500" />
                <span className="font-semibold text-ink-900">
                  {new Date(x.date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                </span>
                {x.reason && <span className="text-ink-500">· {x.reason}</span>}
                <button type="button" onClick={() => remove(x)}
                  className="grid h-4 w-4 shrink-0 place-items-center rounded-full text-ink-400 transition hover:bg-marigold-200 hover:text-ink-700"
                  aria-label={`Remove day off on ${x.date}`}>
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/* ---------------- small inline icons ---------------- */

function PlusIcon() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M8 3v10M3 8h10" strokeLinecap="round" />
    </svg>
  );
}

function CopyIcon() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.2" />
      <path d="M3 10.5V3.7A1.2 1.2 0 0 1 4.2 2.5h6.8" strokeLinecap="round" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M3 8.5 6.5 12 13 4.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg className="h-3 w-3 shrink-0" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.8V8l2.2 1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
