import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDownIcon, CheckIcon } from "@heroicons/react/20/solid";
import { catalogFilterMenuClass, catalogFilterOptionClass, cx, workstationFieldLabelClass, workstationInputClass } from "./panelPrimitives";

interface Props {
  label: string;
  value: string;
  options: { value: string; label: string; keywords?: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
  required?: boolean;
  customHint: string;
}

/** Editable product fields: selecting a known value is optional. */
export default function Combobox({ label, value, options, onChange, disabled = false, required = false, customHint }: Props) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [position, setPosition] = useState({ top: 0, left: 0, width: 0, maxHeight: 240 });
  const matches = useMemo(() => {
    const query = value.trim().toLocaleLowerCase();
    return options.filter(option => `${option.label} ${option.value} ${option.keywords || ""}`.toLocaleLowerCase().includes(query));
  }, [options, value]);
  const place = useCallback(() => {
    const rect = input.current?.getBoundingClientRect();
    if (!rect) return;
    const padding = 12;
    const height = Math.min(240, Math.max(1, matches.length) * 36 + 16);
    const below = window.innerHeight - rect.bottom - padding;
    const above = rect.top - padding;
    const upwards = below < height && above > below;
    const maxHeight = Math.max(0, Math.min(height, (upwards ? above : below) - 6));
    const width = Math.min(rect.width, window.innerWidth - padding * 2);
    setPosition({ top: upwards ? rect.top - maxHeight - 6 : rect.bottom + 6,
      left: Math.max(padding, Math.min(rect.left, window.innerWidth - width - padding)), width, maxHeight });
  }, [matches.length]);
  useEffect(() => {
    if (!open) return;
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, place]);
  useEffect(() => {
    if (open && active >= 0) document.getElementById(`${id}-option-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [open, active, id]);
  const choose = (next: string) => { onChange(next); input.current?.focus(); setOpen(false); };
  return <div className="grid min-w-0 gap-1.5">
    <label htmlFor={id} className={workstationFieldLabelClass}>{label}{required ? " *" : ""}</label>
    <div className="relative min-w-0">
      <input id={id} ref={input} role="combobox" value={value} required={required} disabled={disabled}
        aria-expanded={open && !disabled} aria-controls={`${id}-list`} aria-autocomplete="list"
        aria-activedescendant={open && matches[active] ? `${id}-option-${active}` : undefined}
        autoComplete="off" autoCorrect="off" autoCapitalize="none" spellCheck={false} maxLength={200} className={`${workstationInputClass} pr-10`}
        onFocus={() => { place(); setOpen(true); }}
        onClick={() => { place(); setOpen(true); }}
        onBlur={() => setOpen(false)}
        onChange={event => { onChange(event.target.value); setActive(-1); setOpen(true); }}
        onKeyDown={event => {
          if (event.key === "Escape" && open) { event.preventDefault(); event.stopPropagation(); setOpen(false); }
          if (event.key === "Enter" && open) {
            event.preventDefault();
            if (matches[active]) choose(matches[active].value); else setOpen(false);
          }
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault(); place(); setOpen(true);
            setActive(index => Math.max(0, Math.min(matches.length - 1, index + (event.key === "ArrowDown" ? 1 : -1))));
          }
        }} />
      <ChevronDownIcon aria-hidden="true" className={cx("pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400 transition-transform duration-200", open && "rotate-180")} />
    </div>
    {open && !disabled && createPortal(
      <div className={catalogFilterMenuClass} style={{ position: "fixed", top: position.top, left: position.left, width: position.width }}>
        <div id={`${id}-list`} role="listbox" aria-label={label} className="overflow-y-auto overscroll-contain p-2" style={{ maxHeight: position.maxHeight }}>
          {matches.length ? matches.map((option, index) => <button key={option.value} type="button" role="option" tabIndex={-1}
            id={`${id}-option-${index}`} aria-selected={option.value === value}
            onMouseDown={event => event.preventDefault()} onClick={() => choose(option.value)}
            className={cx(catalogFilterOptionClass, index === active && "bg-[var(--surface-well)]")}>
            <span className="min-w-0 flex-1 break-words">{option.label}</span>
            <CheckIcon aria-hidden="true" className={cx("h-4 w-4 shrink-0", option.value !== value && "invisible")} />
          </button>) : <p className="px-2 py-2 text-xs text-slate-500 dark:text-slate-400">{customHint}</p>}
        </div>
      </div>, document.body,
    )}
  </div>;
}
