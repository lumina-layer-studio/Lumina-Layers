import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDownIcon } from "@heroicons/react/20/solid";
import { useI18n } from "../../i18n/context";
import { filamentMatches } from "../../utils/filamentIdentity";
import { EMPTY_RESOURCE_FILTERS, RESOURCE_AXES, hasResourceFilters, type ResourceAxis, type ResourceFacets, type ResourceFilters } from "../../utils/resourceSearch";
import { catalogFilterMenuClass, catalogFilterOptionClass, catalogFilterTriggerClass, compactFieldClass, cx } from "./panelPrimitives";
import { LibraryBrandLogo } from "./LibraryDetails";
import Button from "./Button";
import { CheckboxIndicator } from "./Checkbox";

function FacetMenu({ axis, label, options, selected, onChange, onOpen, complete, hint }: {
  axis: ResourceAxis; label: string; options: ResourceFacets[ResourceAxis]; selected: string[];
  onChange: (selected: string[]) => void; onOpen?: () => void; complete: boolean; hint?: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState({ top: 0, left: 0, width: 280, maxHeight: 320 });
  const trigger = useRef<HTMLButtonElement>(null), menu = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  const close = () => { setOpen(false); trigger.current?.focus(); };
  useEffect(() => {
    if (!open) return;
    const place = () => {
      const bounds = trigger.current?.getBoundingClientRect();
      if (!bounds) return;
      const width = Math.min(280, window.innerWidth - 24);
      const below = window.innerHeight - bounds.bottom - 16;
      const above = below < 220 && bounds.top > below;
      const maxHeight = Math.min(360, Math.max(120, above ? bounds.top - 20 : below));
      setPosition({ width, maxHeight, top: above ? bounds.top - maxHeight - 6 : bounds.bottom + 6,
        left: Math.max(12, Math.min(bounds.left, window.innerWidth - width - 12)) });
    };
    place();
    input.current?.focus();
    const dismiss = (event: Event) => {
      if (!trigger.current?.contains(event.target as Node) && !menu.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", dismiss);
    document.addEventListener("focusin", dismiss);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      document.removeEventListener("mousedown", dismiss);
      document.removeEventListener("focusin", dismiss);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);
  const values = options.map((option) => option.value);
  const allOptions: ResourceFacets[ResourceAxis] = [...options, ...selected.filter((value) => !values.includes(value)).map((value) => ({ value, label: value, count: 0 }))];
  const visible = allOptions.filter((option) => filamentMatches(query, `${option.label} ${option.terms ?? ""}`));
  const summary = selected.map((value) => allOptions.find((option) => option.value === value)?.label ?? value);
  return <>
    <button ref={trigger} type="button" aria-label={label} aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? id : undefined}
      className={cx(catalogFilterTriggerClass, "max-w-56")}
      data-active={selected.length || open ? "true" : undefined}
      onClick={() => { if (!open) { setQuery(""); onOpen?.(); } setOpen(!open); }}>
      <span className="shrink-0">{label}</span>
      {summary.length > 0 && <span className="truncate font-medium">{summary.length === 1 ? summary[0] : summary.length}</span>}
      <ChevronDownIcon aria-hidden="true" className={cx("h-4 w-4 shrink-0 text-slate-400 transition-transform duration-200 dark:text-slate-500", open && "rotate-180")} />
    </button>
    {open && createPortal(<div ref={menu} id={id} role="dialog" aria-label={label}
      onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); close(); } }}
      style={{ position: "fixed", ...position }} className={cx(catalogFilterMenuClass, "flex flex-col p-2")}>
      <input ref={input} value={query} onChange={(event) => setQuery(event.target.value)}
        autoCorrect="off" autoCapitalize="none" spellCheck={false}
        aria-label={t("resources_filter_search").replace("{field}", label)} placeholder={t("resources_filter_search").replace("{field}", label)}
        className={compactFieldClass} />
      {hint && <p className="px-2 pt-2 text-[11px] text-slate-500">{hint}</p>}
      {!complete && <p role="status" className="px-2 pt-2 text-xs text-slate-500">{t("resources_filter_loading")}</p>}
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1">
        {visible.map((option) => {
          const checked = selected.includes(option.value);
          return <label key={option.value} className={cx(catalogFilterOptionClass, "relative cursor-pointer", !option.count && !checked && complete && "opacity-45")}>
            <input type="checkbox" className="peer sr-only" checked={checked} disabled={complete && !option.count && !checked}
              onChange={() => onChange(checked ? selected.filter((value) => value !== option.value) : [...selected, option.value])} />
            <CheckboxIndicator checked={checked} />
            {axis === "brand" && <span aria-hidden="true" className="inline-flex h-7 w-16 shrink-0">
              <LibraryBrandLogo logo={option.logo} size="sm" />
            </span>}
            {option.swatch && <span aria-hidden="true" className="h-3 w-3 rounded-full border border-black/15" style={{ backgroundColor: option.swatch }} />}
            <span className="min-w-0 flex-1 break-words">{axis === "count" ? t("resources_color_count").replace("{count}", option.label) : option.label}</span>
            {complete && <span className="text-xs tabular-nums text-slate-500">{option.count}</span>}
          </label>;
        })}
        {complete && !visible.length && <p className="p-2 text-xs text-slate-500">{t("resources_filter_no_options")}</p>}
      </div>
      <div className="flex shrink-0 justify-between border-t panel-divider pt-2">
        <Button size="sm" variant="ghost" label={t("resources_clear_filters")} disabled={!selected.length} onClick={() => onChange([])} />
        <Button size="sm" label={t("resources_filter_done")} onClick={close} />
      </div>
    </div>, document.body)}
  </>;
}

export default function ResourceCatalogFilters({ kind, filters, facets, onChange, onOpen, complete = true }: {
  kind: "materials" | "luts"; filters: ResourceFilters; facets: ResourceFacets;
  onChange: (filters: ResourceFilters) => void; onOpen?: () => void; complete?: boolean;
}) {
  const { t } = useI18n();
  return <div role="group" aria-label={t("resources_filter_group")} className="flex w-full min-w-0 flex-wrap items-center gap-1">
    {RESOURCE_AXES.filter((axis) => kind === "luts" || axis !== "count").map((axis) => <FacetMenu key={axis} axis={axis}
      label={t(`resources_filter_${axis}`)} options={facets[axis]} selected={filters[axis]} complete={complete}
      hint={axis === "color" ? t(kind === "luts" ? "resources_filter_lut_colors_hint" : "resources_filter_color_hint") : undefined}
      onOpen={onOpen} onChange={(value) => onChange({ ...filters, [axis]: value })} />)}
    {hasResourceFilters(filters) && <Button size="sm" variant="ghost" label={t("resources_clear_filters")} onClick={() => onChange(EMPTY_RESOURCE_FILTERS)} />}
  </div>;
}
