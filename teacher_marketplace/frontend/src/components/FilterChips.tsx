/**
 * Active filters as removable chips.
 *
 * Filters that live only inside a collapsed panel become invisible state:
 * a student sees three results, cannot remember why, and blames the
 * marketplace for being empty. Showing every active filter as something you
 * can dismiss in one tap makes the narrowing recoverable.
 */

export interface ActiveFilter {
  key: string;
  label: string;
  onClear: () => void;
}

export function FilterChips({ filters, onClearAll }: { filters: ActiveFilter[]; onClearAll?: () => void }) {
  if (!filters.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {filters.map((f) => (
        <button
          key={f.key}
          type="button"
          onClick={f.onClear}
          className="group inline-flex items-center gap-1.5 rounded-full border-[1.5px] border-pine-600 bg-pine-50 py-1 pl-3 pr-2 text-[0.8125rem] font-semibold text-pine-800 transition hover:bg-pine-100"
        >
          {f.label}
          <span
            aria-hidden="true"
            className="grid h-4 w-4 place-items-center rounded-full bg-pine-600 text-[10px] leading-none text-white transition group-hover:bg-pine-800"
          >
            ×
          </span>
          <span className="sr-only">Remove filter</span>
        </button>
      ))}
      {filters.length > 1 && onClearAll && (
        <button type="button" onClick={onClearAll} className="u-link text-[0.8125rem]">
          Clear all
        </button>
      )}
    </div>
  );
}
