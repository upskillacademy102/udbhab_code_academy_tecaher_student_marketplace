import { useEffect, useMemo, useRef, useState } from "react";

/**
 * Type-to-filter search box for a subject/language pick — a React port of
 * the combobox half of static/js/picker.js (the Alpine version used on the
 * landing/sign-up pages), so the two implementations share one behaviour
 * instead of drifting apart.
 *
 * Replaces showing every option as a wall of chips: once a taxonomy list
 * runs into the dozens, a chip grid is no longer "pick one at a glance," it's
 * a scavenger hunt. A search bar scales to any list length the same way.
 *
 * Matching mirrors picker.js exactly: names starting with the query rank
 * before names merely containing it, capped at 50 results so the listbox is
 * never unbounded.
 */

const MAX_RESULTS = 50;

function filterOptions(items: string[], query: string): string[] {
  const q = query.trim().toLowerCase();
  if (!q) return items.slice(0, MAX_RESULTS);
  const starts: string[] = [];
  const contains: string[] = [];
  for (const item of items) {
    const n = item.toLowerCase();
    if (n.startsWith(q)) starts.push(item);
    else if (n.includes(q)) contains.push(item);
  }
  return [...starts, ...contains].slice(0, MAX_RESULTS);
}

export function TaxonomyCombobox({
  id, items, value, onChange, placeholder, emptyHint,
}: {
  id: string;
  items: string[];
  value: string | null;
  onChange: (v: string | null) => void;
  placeholder: string;
  /** Shown when the taxonomy list itself is empty (nothing to search). */
  emptyHint?: string;
}) {
  const [query, setQuery] = useState(value ?? "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);

  // Keep the input's text in sync with the real selection whenever it
  // changes from outside (cleared by a filter chip, reset, etc.).
  useEffect(() => {
    setQuery(value ?? "");
  }, [value]);

  const options = useMemo(() => filterOptions(items, query), [items, query]);

  function commit(v: string | null) {
    onChange(v);
    setQuery(v ?? "");
    setOpen(false);
    setActive(-1);
  }

  function closeAndRevert() {
    setOpen(false);
    setActive(-1);
    setQuery(value ?? "");
  }

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) closeAndRevert();
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, value]);

  if (!items.length) return <p className="u-fine">{emptyHint}</p>;

  const listboxId = `${id}-listbox`;
  const activeId = open && active >= 0 ? `${id}-opt-${active}` : undefined;

  return (
    <div className="u-combo" ref={rootRef}>
      <input
        type="text"
        id={id}
        className="u-input"
        role="combobox"
        aria-autocomplete="list"
        aria-controls={listboxId}
        aria-expanded={open}
        aria-activedescendant={activeId}
        autoComplete="off"
        placeholder={placeholder}
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          const v = e.target.value;
          setQuery(v);
          setOpen(true);
          setActive(-1);
          if (!v) onChange(null);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            if (!open) { setOpen(true); setActive(0); return; }
            setActive((a) => (options.length ? (a + 1) % options.length : -1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            if (!open) { setOpen(true); setActive(options.length - 1); return; }
            setActive((a) => (options.length ? (a - 1 + options.length) % options.length : -1));
          } else if (e.key === "Enter") {
            e.preventDefault();
            if (open && active >= 0 && options[active]) commit(options[active]);
            else if (options.length === 1) commit(options[0]!);
            else setOpen(false);
          } else if (e.key === "Escape") {
            if (open) closeAndRevert();
            else setQuery("");
          }
        }}
      />

      {open && options.length > 0 && (
        <ul id={listboxId} role="listbox" aria-label={placeholder} className="u-combo-list">
          {options.map((opt, i) => (
            <li
              key={opt}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={active === i}
              data-active={active === i}
              className="u-combo-opt"
              onMouseDown={(e) => e.preventDefault()}
              onMouseMove={() => setActive(i)}
              onClick={() => commit(opt)}
            >
              {opt}
            </li>
          ))}
        </ul>
      )}

      {open && query && options.length === 0 && (
        <p className="u-hint mt-1.5">No match for &ldquo;{query}&rdquo;.</p>
      )}
    </div>
  );
}
