import { DAYS, blankTimeWindow, type TimeWindow } from "@/lib/intent";

/**
 * "When are you free?" as a list of specific day+time windows (Monday
 * 7-8pm, Tuesday 8-9am, ...) plus an "I'm flexible" escape — shared by
 * Discover and Search so both filter panels behave identically.
 *
 * Each window has ITS OWN time, unlike the older days[] + one shared
 * band picker this replaced: a student free Monday evenings and Tuesday
 * mornings could never express that with one band applied to both days.
 */
export function WindowPicker({
  windows, flexible, onChange, onToggleFlexible,
}: {
  windows: TimeWindow[];
  flexible: boolean;
  onChange: (windows: TimeWindow[]) => void;
  onToggleFlexible: () => void;
}) {
  const setWindow = (i: number, patch: Partial<TimeWindow>) =>
    onChange(windows.map((w, j) => (j === i ? { ...w, ...patch } : w)));
  const removeWindow = (i: number) => onChange(windows.filter((_, j) => j !== i));
  const addWindow = () => onChange([...windows, blankTimeWindow()]);

  return (
    <div>
      <button type="button" aria-pressed={flexible} onClick={onToggleFlexible}
        className={
          "flex w-full max-w-sm items-start gap-2.5 rounded-xl border-[1.5px] px-3.5 py-2.5 text-left transition duration-150 ease-enter " +
          (flexible
            ? "border-pine-600 bg-pine-50"
            : "border-ink-300 bg-paper hover:border-pine-400 hover:bg-pine-50")
        }>
        <span
          className={
            "mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full border-[1.5px] " +
            (flexible ? "border-pine-600 bg-pine-600" : "border-ink-300")
          }>
          {flexible && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
        </span>
        <span>
          <span className="block text-[0.875rem] font-semibold text-ink-900">I'm flexible</span>
          <span className="block text-[0.75rem] text-ink-500">
            No fixed time — show every match and I'll work around the teacher's hours.
          </span>
        </span>
      </button>

      {!flexible && (
        <div className="mt-3 flex max-w-sm flex-col gap-2">
          {windows.map((w, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <select className="u-select min-h-[40px] flex-[1.3] py-1.5" value={w.day}
                onChange={(e) => setWindow(i, { day: Number(e.target.value) })} aria-label={`Day ${i + 1}`}>
                {DAYS.map((d) => <option key={d.n} value={d.n}>{d.full}</option>)}
              </select>
              <input type="time" step={900} className="u-input min-h-[40px] flex-1 py-1.5" value={w.start}
                onChange={(e) => setWindow(i, { start: e.target.value })} aria-label={`Start time ${i + 1}`} />
              <span className="text-[0.75rem] text-ink-500">–</span>
              <input type="time" step={900} className="u-input min-h-[40px] flex-1 py-1.5" value={w.end}
                onChange={(e) => setWindow(i, { end: e.target.value })} aria-label={`End time ${i + 1}`} />
              <button type="button" className="u-btn-ghost u-btn-sm shrink-0 text-danger" onClick={() => removeWindow(i)}
                aria-label={`Remove window ${i + 1}`}>✕</button>
            </div>
          ))}
          <button type="button" className="u-link self-start text-[0.8125rem]" onClick={addWindow}>
            {windows.length ? "+ Add another day/time" : "+ Add a day/time you're free"}
          </button>
        </div>
      )}
    </div>
  );
}
