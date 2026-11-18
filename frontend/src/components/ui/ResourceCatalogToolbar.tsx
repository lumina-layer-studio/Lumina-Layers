import type { ReactNode } from "react";
import { MagnifyingGlassIcon } from "@heroicons/react/24/outline";
import { catalogFilterTriggerClass, cx, workstationInputClass } from "./panelPrimitives";

export function ResourceInstallFilters<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string; count: number | null | undefined }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex max-w-full flex-wrap items-center gap-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={catalogFilterTriggerClass}
        >
          <span>{option.label}</span>
          <span className="text-[11px] tabular-nums opacity-70">{option.count ?? "…"}</span>
        </button>
      ))}
    </div>
  );
}

export default function ResourceCatalogToolbar({
  query,
  searchLabel,
  onQueryChange,
  actions,
  status,
  children,
}: {
  query: string;
  searchLabel: string;
  onQueryChange: (query: string) => void;
  actions?: ReactNode;
  status?: ReactNode;
  children: ReactNode;
}) {
  return (
    <search className="flex w-full min-w-0 flex-col gap-2.5">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <div className="relative min-w-[min(100%,16rem)] flex-1 basis-72">
          <MagnifyingGlassIcon
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400 dark:text-slate-500"
          />
          <input
            type="search"
            name="q"
            autoCorrect="off"
            autoCapitalize="none"
            spellCheck={false}
            aria-label={searchLabel}
            placeholder={searchLabel}
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            className={cx(workstationInputClass, "min-h-10 pl-9")}
          />
        </div>
        {actions && <div className="flex max-w-full flex-wrap items-center gap-1">{actions}</div>}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5">
        {status}
        {status && (
          <span
            aria-hidden="true"
            className="hidden h-4 w-px bg-[var(--surface-divider)] sm:inline-block"
          />
        )}
        <div className="min-w-0 max-w-full">{children}</div>
      </div>
    </search>
  );
}
