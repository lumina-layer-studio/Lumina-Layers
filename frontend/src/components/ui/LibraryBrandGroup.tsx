import DisclosureChevron from "./DisclosureChevron";
import type { ReactNode } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useI18n } from "../../i18n/context";
import { tRuntime } from "../../i18n/runtime";
import { HeaderTooltip } from "./HeaderTooltip";
import { LibraryBrandLogo } from "./LibraryDetails";
import { POLYMAKER_PANCHROMA_LOGO } from "../../data/filamentBrands";

interface LibraryBrandHeaderProps {
  label: string;
  logo?: string;
  count: number;
  countLabel?: string;
  testIdPrefix?: string;
  collapsed: boolean;
  pinned: boolean;
  onToggle?: () => void;
  onPin?: () => void;
  onMove?: (direction: number) => void;
  dragging?: boolean;
}

export function LibraryBrandHeader({ label, logo, count, countLabel, testIdPrefix = "material-library", collapsed, pinned, onToggle, onPin, onMove, dragging = false }: LibraryBrandHeaderProps) {
  const { t } = useI18n();
  const preview = !onToggle;
  return (
    <div className="flex min-w-0 items-center gap-1 rounded-lg">
      <HeaderTooltip label={t("mat_gradient_library_reorder_hint")} suppressed={preview || dragging} className="min-w-0 flex-1">
      <button type="button" tabIndex={preview ? -1 : 0}
        data-testid={preview ? undefined : `${testIdPrefix}-brand-group-toggle`}
        aria-expanded={!collapsed} onClick={onToggle}
        onKeyDown={(event) => {
          if (event.key === "ArrowUp" || event.key === "ArrowDown") {
            event.preventDefault();
            onMove?.(event.key === "ArrowUp" ? -1 : 1);
          }
        }}
        className="material-library-group flex min-w-0 flex-1 cursor-grab items-center justify-between gap-3 rounded-lg px-2 py-2 text-left active:cursor-grabbing">
        <span className="flex min-w-0 flex-wrap items-center gap-3">
          <LibraryBrandLogo logo={logo === POLYMAKER_PANCHROMA_LOGO ? undefined : logo} />
          <span className="truncate text-sm font-semibold text-slate-600 dark:text-slate-300">{label}</span>
          <span className="rounded-full border border-slate-200/80 px-2 py-0.5 text-xs font-semibold text-slate-500 dark:border-slate-700/80 dark:text-slate-400">{countLabel ?? tRuntime("mat_gradient_library_brand_count", { count })}</span>
        </span>
        <DisclosureChevron expanded={!collapsed} />
      </button>
      </HeaderTooltip>
      <HeaderTooltip label={t(pinned ? "mat_gradient_library_unpin_hint" : "library_pin_hint")} suppressed={preview || dragging}>
      <button type="button" tabIndex={preview ? -1 : 0}
        aria-label={tRuntime(pinned ? "mat_gradient_library_unpin_brand" : "mat_gradient_library_pin_brand", { brand: label })}
        aria-pressed={pinned}
        onPointerDown={(event) => event.stopPropagation()} onClick={onPin}
        className={`shrink-0 rounded-lg p-2 text-slate-600 hover:bg-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-slate-300 dark:hover:bg-slate-700 ${pinned ? "bg-slate-200 dark:bg-slate-700" : ""}`}>
        <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill={pinned ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 3h6l-1 6 4 4v2H6v-2l4-4-1-6Z" /><path d="M12 15v6" />
        </svg>
      </button>
      </HeaderTooltip>
    </div>
  );
}

export function SortableLibraryBrand({ groupKey, brand, children, testIdPrefix = "material-library", ...header }: LibraryBrandHeaderProps & { groupKey: string; brand: string | null; children: ReactNode }) {
  const { setNodeRef, setActivatorNodeRef, listeners, transform, transition, isDragging } = useSortable({ id: groupKey });
  return (
    <section ref={setNodeRef} data-testid={`${testIdPrefix}-brand-group`} data-brand={brand ?? ""}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.25 : 1 }}
      className="grid gap-3">
      <div ref={setActivatorNodeRef} {...listeners} className="touch-none select-none cursor-grab rounded-lg active:cursor-grabbing">
        <LibraryBrandHeader {...header} testIdPrefix={testIdPrefix} dragging={isDragging} />
      </div>
      {children}
    </section>
  );
}
